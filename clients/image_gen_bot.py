"""

多线程 GPT 图像生成机器人

通过 OpenAI 兼容 API 使用 gpt-image-2 模型生成图像。

"""



import base64
import gc
import json
import logging
import os
import random
import threading
import time
from datetime import datetime
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter



# ---------------------------------------------------------------------------

# 日志配置

# ---------------------------------------------------------------------------

logging.basicConfig(

    level=logging.INFO,

    format="%(asctime)s [%(threadName)s] %(levelname)s %(message)s",

    datefmt="%Y-%m-%d %H:%M:%S",

)

logger = logging.getLogger(__name__)



# ---------------------------------------------------------------------------

# 配置加载

# ---------------------------------------------------------------------------



def load_config(config_path: str = "config.json") -> dict:

    config_file = Path(config_path)

    if not config_file.exists():

        raise FileNotFoundError(f"配置文件未找到: {config_path}")

    with open(config_file, "r", encoding="utf-8") as f:

        return json.load(f)



def parse_thread_ramp_config(rt_cfg: dict) -> dict:

    """解析线程扩容配置，兼容旧的 thread_count 字段。"""

    if "thread_count" in rt_cfg and "initial_thread_count" not in rt_cfg:

        count = int(rt_cfg["thread_count"])

        return {

            "initial_thread_count": count,

            "thread_ramp_interval_seconds": 0,

            "threads_per_ramp": 0,

            "max_thread_count": count,

        }



    initial = int(rt_cfg["initial_thread_count"])

    interval = float(rt_cfg["thread_ramp_interval_seconds"])

    per_ramp = int(rt_cfg["threads_per_ramp"])

    max_count = int(rt_cfg["max_thread_count"])



    if initial < 1:

        raise ValueError("initial_thread_count 必须 >= 1")

    if max_count < initial:

        raise ValueError("max_thread_count 不能小于 initial_thread_count")

    if interval < 0:

        raise ValueError("thread_ramp_interval_seconds 不能为负数")

    if per_ramp < 0:

        raise ValueError("threads_per_ramp 不能为负数")

    if interval == 0 and per_ramp > 0:

        raise ValueError("threads_per_ramp > 0 时需要设置 thread_ramp_interval_seconds > 0")



    return {

        "initial_thread_count": initial,

        "thread_ramp_interval_seconds": interval,

        "threads_per_ramp": per_ramp,

        "max_thread_count": max_count,

    }



# ---------------------------------------------------------------------------

# 统计数据类（由锁保护的普通字典）

# ---------------------------------------------------------------------------



class GlobalStats:

    def __init__(self):

        self.success = 0

        self.failure = 0

        self.start_time = time.time()

        self.response_time_sum = 0.0

        self.response_time_count = 0

        self.response_time_min: float | None = None

        self.response_time_max: float | None = None

        self.thread_count = 0

        self._lock = threading.Lock()



    def set_thread_count(self, count: int) -> None:

        with self._lock:

            self.thread_count = count



    def record_call(self, success: bool, response_time: float) -> bool:

        """记录一次调用，返回是否达到统计里程碑（每 10 次总调用）。"""

        with self._lock:

            if success:

                self.success += 1

            else:

                self.failure += 1

            self.response_time_sum += response_time

            self.response_time_count += 1

            if self.response_time_min is None or response_time < self.response_time_min:

                self.response_time_min = response_time

            if self.response_time_max is None or response_time > self.response_time_max:

                self.response_time_max = response_time

            total = self.success + self.failure

            return total % 10 == 0



    def snapshot(self) -> dict:

        with self._lock:

            elapsed = time.time() - self.start_time

            total = self.success + self.failure

            avg_success_per_min = (self.success / elapsed * 60) if elapsed > 0 else 0

            success_rate = (self.success / total * 100) if total > 0 else 0

            avg_response_time = (

                self.response_time_sum / self.response_time_count

                if self.response_time_count > 0 else 0

            )

            return {

                "success": self.success,

                "failure": self.failure,

                "total_calls": total,

                "thread_count": self.thread_count,

                "elapsed_seconds": round(elapsed, 2),

                "avg_success_per_minute": round(avg_success_per_min, 4),

                "success_rate_pct": round(success_rate, 2),

                "avg_response_time": round(avg_response_time, 2),

                "min_response_time": round(self.response_time_min, 2) if self.response_time_min is not None else 0,

                "max_response_time": round(self.response_time_max, 2) if self.response_time_max is not None else 0,

            }



# ---------------------------------------------------------------------------

# 图像生成

# ---------------------------------------------------------------------------

_thread_local = threading.local()


def _get_http_session() -> requests.Session:
    """每个工作线程复用独立 Session，避免全局连接池无限膨胀。"""
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = requests.Session()
        adapter = HTTPAdapter(pool_connections=1, pool_maxsize=1, max_retries=0)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        _thread_local.session = session
    return session


def _close_http_session() -> None:
    session = getattr(_thread_local, "session", None)
    if session is not None:
        session.close()
        _thread_local.session = None


def _parse_png_size(img_bytes: bytes) -> tuple[int, int] | None:
    if len(img_bytes) >= 24 and img_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        w = int.from_bytes(img_bytes[16:20], "big")
        h = int.from_bytes(img_bytes[20:24], "big")
        return w, h
    return None


def _parse_jpeg_size(img_bytes: bytes) -> tuple[int, int] | None:
    if len(img_bytes) < 4 or img_bytes[:2] != b"\xff\xd8":
        return None

    i = 2
    while i < len(img_bytes) - 9:
        if img_bytes[i] != 0xFF:
            i += 1
            continue
        marker = img_bytes[i + 1]
        if marker in (
            0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
            0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
        ):
            h = int.from_bytes(img_bytes[i + 5:i + 7], "big")
            w = int.from_bytes(img_bytes[i + 7:i + 9], "big")
            return w, h
        if marker in (0xD8, 0xD9):
            i += 2
            continue
        if i + 3 >= len(img_bytes):
            break
        seg_len = int.from_bytes(img_bytes[i + 2:i + 4], "big")
        if seg_len < 2:
            break
        i += 2 + seg_len
    return None


def _parse_image_size(img_bytes: bytes) -> tuple[int, int] | None:
    """只读文件头解析尺寸，避免 PIL 解码导致内存无法回收。"""
    return _parse_png_size(img_bytes) or _parse_jpeg_size(img_bytes)


def check_image_size(img_bytes: bytes, expected_size: str) -> tuple[bool, str | None]:
    """校验生成图片的实际尺寸是否与期望一致。"""
    try:
        expected_w, expected_h = (int(part) for part in expected_size.lower().split("x", 1))
    except ValueError:
        return False, f"期望尺寸格式无效: {expected_size}"

    actual = _parse_image_size(img_bytes)
    if actual is None:
        return False, "图片尺寸检测失败: 无法识别 PNG/JPEG 文件头"

    actual_w, actual_h = actual
    if actual_w == expected_w and actual_h == expected_h:
        return True, None
    return False, f"图片尺寸不符: 期望 {expected_w}x{expected_h}, 实际 {actual_w}x{actual_h}"


def generate_image(base_url: str, api_key: str, model: str, prompt: str,
                   size: str, quality: str) -> tuple[bool, float, str | None, bytes | None]:
    """
    调用 OpenAI 兼容的图像生成接口。
    返回 (是否成功, 响应耗时秒数, 错误信息, 解码后的图片 bytes)。
    """

    start = time.time()

    url = f"{base_url.rstrip('/')}/images/generations"

    headers = {

        "Authorization": f"Bearer {api_key}",

        "Content-Type": "application/json",

    }

    payload = {

        "model": model,

        "prompt": prompt,

        "n": 1,

        "size": size,

        "quality": quality,

        "response_format": "b64_json",

    }

    session = _get_http_session()
    resp = None

    try:

        resp = session.post(url, headers=headers, json=payload, timeout=2000)

        resp.raise_for_status()

        data = resp.json()

        b64_json = data["data"][0].get("b64_json")
        del data

        if b64_json:
            img_bytes = base64.b64decode(b64_json)
            del b64_json

            size_ok, size_error = check_image_size(img_bytes, size)
            if not size_ok:
                del img_bytes
                logger.error(size_error)
                return False, time.time() - start, size_error, None
            return True, time.time() - start, None, img_bytes

        error_msg = "响应解析错误: 缺少 b64_json 字段"

        logger.error(error_msg)

        return False, time.time() - start, error_msg, None

    except requests.exceptions.HTTPError as e:
        resp = e.response
        detail = ""
        if resp is not None:
            try:
                body = resp.json()
                err = body.get("error") if isinstance(body, dict) else None
                if isinstance(err, dict):
                    detail = str(err.get("message") or err.get("code") or "")
                elif isinstance(body, dict) and body.get("error"):
                    detail = str(body["error"])
            except ValueError:
                detail = (resp.text or "").strip()[:300]
        error_msg = f"HTTP 错误: {e}" + (f" – {detail}" if detail else "")

        logger.error(error_msg)

        return False, time.time() - start, error_msg, None

    except requests.exceptions.RequestException as e:

        error_msg = f"请求错误: {e}"

        logger.error(error_msg)

        return False, time.time() - start, error_msg, None

    except (KeyError, IndexError, ValueError) as e:

        error_msg = f"响应解析错误: {e}"

        logger.error(error_msg)

        return False, time.time() - start, error_msg, None

    finally:
        if resp is not None:
            resp.close()



# ---------------------------------------------------------------------------

# 统计数据持久化

# ---------------------------------------------------------------------------



def format_stats_text(snap: dict, label: str = "periodic") -> str:

    label_cn = "定期" if label == "periodic" else "最终"

    lines = [

        f"=== [{label_cn}] 全局统计 @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===",

        f"  调用成功数      : {snap['success']}",

        f"  调用失败数      : {snap['failure']}",

        f"  总调用次数      : {snap['total_calls']}",

        f"  当前线程数      : {snap['thread_count']}",

        f"  运行总时间(秒)  : {snap['elapsed_seconds']}",

        f"  平均成功/分钟   : {snap['avg_success_per_minute']}",

        f"  成功率          : {snap['success_rate_pct']}%",

        f"  响应平均时间(秒): {snap['avg_response_time']}",

        f"  响应最大时间(秒): {snap['max_response_time']}",

        f"  响应最小时间(秒): {snap['min_response_time']}",

        "",

    ]

    return "\n".join(lines)



def write_stats(stats_path: Path, stats: GlobalStats, label: str = "periodic"):

    text = format_stats_text(stats.snapshot(), label=label)

    logger.info(text.strip())

    with open(stats_path, "a", encoding="utf-8") as f:

        f.write(text + "\n")



_error_log_lock = threading.Lock()



_image_save_lock = threading.Lock()


def save_generated_image(img_bytes: bytes, output_dir: Path) -> Path | None:
    """将图片 bytes 保存到 output_dir，文件名以时间戳命名。"""
    try:
        with _image_save_lock:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            path = output_dir / f"{ts}.png"
            while path.exists():
                ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                path = output_dir / f"{ts}.png"
            with open(path, "wb") as f:
                f.write(img_bytes)
        return path
    except Exception as e:
        logger.error("保存图片失败: %s", e)
        return None


def write_error_log(error_path: Path, thread_id: int, response_time: float, error_msg: str, prompt: str):

    """将失败日志写入 error.txt，每行一条，行首为耗时。"""

    safe_msg = error_msg.replace("\n", " ").replace("\r", " ")

    safe_prompt = prompt.replace("\n", " ").replace("\r", " ")

    line = f"{response_time:.2f}s | 线程-{thread_id:02d} | {safe_msg} | 提示词: {safe_prompt}"

    with _error_log_lock:

        with open(error_path, "a", encoding="utf-8") as f:

            f.write(line + "\n")



# ---------------------------------------------------------------------------

# 工作线程

# ---------------------------------------------------------------------------



def worker(thread_id: int, config: dict, stop_event: threading.Event,

           output_dir: Path, stats_path: Path, error_path: Path, global_stats: GlobalStats):

    api_cfg = config["api"]

    rt_cfg = config["runtime"]

    out_cfg = config["output"]

    save_to_disk: bool = out_cfg.get("save_images_to_disk", True)

    prompts: list[str] = config["prompts"]



    logger.info("线程-%02d 已启动", thread_id)



    while not stop_event.is_set():

        prompt = random.choice(prompts)

        logger.info("线程-%02d | 提示词: %s", thread_id, prompt[:60])



        success, response_time, error_msg, img_bytes = generate_image(

            base_url=api_cfg["base_url"],

            api_key=api_cfg["api_key"],

            model=api_cfg["model"],

            prompt=prompt,

            size=api_cfg["image_size"],

            quality=api_cfg["image_quality"],

        )



        if success:

            if save_to_disk and img_bytes:
                saved_path = save_generated_image(img_bytes, output_dir)
                if saved_path:
                    logger.info("线程-%02d | 生成成功 (%.2f 秒), 已保存: %s", thread_id, response_time, saved_path.name)
                else:
                    logger.info("线程-%02d | 生成成功 (%.2f 秒), 但保存失败", thread_id, response_time)
            else:
                logger.info("线程-%02d | 生成成功 (%.2f 秒), 未写磁盘", thread_id, response_time)

            hit_milestone = global_stats.record_call(True, response_time)

        else:

            logger.warning("线程-%02d | 图像生成失败 (%.2f 秒)", thread_id, response_time)

            write_error_log(error_path, thread_id, response_time, error_msg or "未知错误", prompt)

            hit_milestone = global_stats.record_call(False, response_time)



        if hit_milestone:

            write_stats(stats_path, global_stats, label="periodic")

            gc.collect()



        img_bytes = None

        # 等待配置的间隔时间后再进行下一次调用（可被中断）

        stop_event.wait(timeout=rt_cfg["call_interval_seconds"])



    _close_http_session()
    logger.info("线程-%02d 已结束", thread_id)



def start_worker(

    thread_id: int,

    config: dict,

    stop_event: threading.Event,

    output_dir: Path,

    stats_path: Path,

    error_path: Path,

    global_stats: GlobalStats,

    threads: list[threading.Thread],

) -> threading.Thread:

    t = threading.Thread(

        target=worker,

        args=(thread_id, config, stop_event, output_dir, stats_path, error_path, global_stats),

        name=f"Worker-{thread_id:02d}",

        daemon=True,

    )

    threads.append(t)

    global_stats.set_thread_count(len(threads))

    t.start()

    return t



def thread_ramp_loop(

    ramp_cfg: dict,

    config: dict,

    stop_event: threading.Event,

    output_dir: Path,

    stats_path: Path,

    error_path: Path,

    global_stats: GlobalStats,

    threads: list[threading.Thread],

    threads_lock: threading.Lock,

    next_thread_id: list[int],

) -> None:

    interval = ramp_cfg["thread_ramp_interval_seconds"]

    per_ramp = ramp_cfg["threads_per_ramp"]

    max_count = ramp_cfg["max_thread_count"]



    while not stop_event.wait(timeout=interval):

        with threads_lock:

            current = len(threads)

            if current >= max_count:

                continue

            to_add = min(per_ramp, max_count - current)

            for _ in range(to_add):

                next_thread_id[0] += 1

                start_worker(

                    next_thread_id[0],

                    config,

                    stop_event,

                    output_dir,

                    stats_path,

                    error_path,

                    global_stats,

                    threads,

                )

            logger.info(

                "线程扩容: 新增 %d 个，当前 %d/%d",

                to_add,

                len(threads),

                max_count,

            )



# ---------------------------------------------------------------------------

# 主入口

# ---------------------------------------------------------------------------



def main():

    script_dir = Path(__file__).parent

    os.chdir(script_dir)



    config = load_config("config.json")

    rt_cfg = config["runtime"]

    out_cfg = config["output"]

    ramp_cfg = parse_thread_ramp_config(rt_cfg)

    total_runtime: int = rt_cfg["total_runtime_seconds"]



    output_dir = Path(out_cfg["base_output_dir"])

    output_dir.mkdir(parents=True, exist_ok=True)

    stats_path = output_dir / out_cfg["stats_filename"]

    error_path = output_dir / "error.txt"

    global_stats = GlobalStats()



    logger.info("正在启动图像生成机器人")

    logger.info("  初始线程数    : %d", ramp_cfg["initial_thread_count"])

    logger.info(

        "  线程扩容      : 每 %.1f 秒增加 %d 个，上限 %d",

        ramp_cfg["thread_ramp_interval_seconds"],

        ramp_cfg["threads_per_ramp"],

        ramp_cfg["max_thread_count"],

    )

    logger.info("  总运行时间    : %d 秒", total_runtime)

    logger.info("  调用间隔      : %s 秒", rt_cfg["call_interval_seconds"])

    logger.info("  模型          : %s", config["api"]["model"])

    logger.info("  已加载提示词  : %d 条", len(config["prompts"]))

    logger.info("  统计/日志目录 : %s", output_dir)

    logger.info("  图片写磁盘    : %s", "是" if out_cfg.get("save_images_to_disk", True) else "否")



    stop_event = threading.Event()

    threads: list[threading.Thread] = []

    threads_lock = threading.Lock()

    next_thread_id = [0]



    for i in range(1, ramp_cfg["initial_thread_count"] + 1):

        start_worker(

            i,

            config,

            stop_event,

            output_dir,

            stats_path,

            error_path,

            global_stats,

            threads,

        )

        next_thread_id[0] = i



    ramp_thread: threading.Thread | None = None

    if (

        ramp_cfg["threads_per_ramp"] > 0

        and ramp_cfg["thread_ramp_interval_seconds"] > 0

        and ramp_cfg["max_thread_count"] > ramp_cfg["initial_thread_count"]

    ):

        ramp_thread = threading.Thread(

            target=thread_ramp_loop,

            args=(

                ramp_cfg,

                config,

                stop_event,

                output_dir,

                stats_path,

                error_path,

                global_stats,

                threads,

                threads_lock,

                next_thread_id,

            ),

            name="ThreadRamp",

            daemon=True,

        )

        ramp_thread.start()



    # 运行指定时长后，向所有线程发送停止信号

    try:

        logger.info("所有线程已运行，将在 %d 秒后停止（按 Ctrl+C 可提前终止）", total_runtime)

        time.sleep(total_runtime)

    except KeyboardInterrupt:

        logger.info("用户中断，正在停止线程...")



    logger.info("正在向所有线程发送停止信号...")

    stop_event.set()



    if ramp_thread is not None:

        ramp_thread.join(timeout=5)



    for t in threads:

        t.join(timeout=30)



    with threads_lock:

        global_stats.set_thread_count(len(threads))

    write_stats(stats_path, global_stats, label="final")

    logger.info("所有线程已停止，运行结束。")





if __name__ == "__main__":

    main()

