"""

多线程 GPT 图像生成机器人

通过 OpenAI 兼容 API 使用 gpt-image-2 模型生成图像。

"""



import base64
import json
import logging
import os
import random
import threading
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image



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

        self._lock = threading.Lock()



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



def check_image_size(b64_json: str, expected_size: str) -> tuple[bool, str | None]:
    """校验生成图片的实际尺寸是否与期望一致。"""
    try:
        expected_w, expected_h = (int(part) for part in expected_size.lower().split("x", 1))
    except ValueError:
        return False, f"期望尺寸格式无效: {expected_size}"

    try:
        img_bytes = base64.b64decode(b64_json)
        with Image.open(BytesIO(img_bytes)) as img:
            actual_w, actual_h = img.size
    except Exception as e:
        return False, f"图片尺寸检测失败: {e}"

    if actual_w == expected_w and actual_h == expected_h:
        return True, None
    return False, f"图片尺寸不符: 期望 {expected_w}x{expected_h}, 实际 {actual_w}x{actual_h}"


def generate_image(base_url: str, api_key: str, model: str, prompt: str,
                   size: str, quality: str) -> tuple[bool, float, str | None, str | None]:
    """
    调用 OpenAI 兼容的图像生成接口。
    返回 (是否成功, 响应耗时秒数, 错误信息, b64_json)。
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

    try:

        resp = requests.post(url, headers=headers, json=payload, timeout=900)

        resp.raise_for_status()

        data = resp.json()

        b64_json = data["data"][0].get("b64_json")
        if b64_json:
            size_ok, size_error = check_image_size(b64_json, size)
            if not size_ok:
                logger.error(size_error)
                return False, time.time() - start, size_error, None
            return True, time.time() - start, None, b64_json

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

           stats_path: Path, error_path: Path, global_stats: GlobalStats):

    api_cfg = config["api"]

    rt_cfg = config["runtime"]

    prompts: list[str] = config["prompts"]



    logger.info("线程-%02d 已启动", thread_id)



    while not stop_event.is_set():

        prompt = random.choice(prompts)

        logger.info("线程-%02d | 提示词: %s", thread_id, prompt[:60])



        success, response_time, error_msg, _ = generate_image(

            base_url=api_cfg["base_url"],

            api_key=api_cfg["api_key"],

            model=api_cfg["model"],

            prompt=prompt,

            size=api_cfg["image_size"],

            quality=api_cfg["image_quality"],

        )



        if success:

            logger.info("线程-%02d | 生成成功 (%.2f 秒)", thread_id, response_time)

            hit_milestone = global_stats.record_call(True, response_time)

        else:

            logger.warning("线程-%02d | 图像生成失败 (%.2f 秒)", thread_id, response_time)

            write_error_log(error_path, thread_id, response_time, error_msg or "未知错误", prompt)

            hit_milestone = global_stats.record_call(False, response_time)



        if hit_milestone:

            write_stats(stats_path, global_stats, label="periodic")



        # 等待配置的间隔时间后再进行下一次调用（可被中断）

        stop_event.wait(timeout=rt_cfg["call_interval_seconds"])



    logger.info("线程-%02d 已结束", thread_id)



# ---------------------------------------------------------------------------

# 主入口

# ---------------------------------------------------------------------------



def main():

    script_dir = Path(__file__).parent

    os.chdir(script_dir)



    config = load_config("config.json")

    rt_cfg = config["runtime"]

    out_cfg = config["output"]

    thread_count: int = rt_cfg["thread_count"]

    total_runtime: int = rt_cfg["total_runtime_seconds"]



    output_dir = Path(out_cfg["base_output_dir"])

    output_dir.mkdir(parents=True, exist_ok=True)

    stats_path = output_dir / out_cfg["stats_filename"]

    error_path = output_dir / "error.txt"

    global_stats = GlobalStats()



    logger.info("正在启动图像生成机器人")

    logger.info("  线程数        : %d", thread_count)

    logger.info("  总运行时间    : %d 秒", total_runtime)

    logger.info("  调用间隔      : %s 秒", rt_cfg["call_interval_seconds"])

    logger.info("  模型          : %s", config["api"]["model"])

    logger.info("  已加载提示词  : %d 条", len(config["prompts"]))

    logger.info("  统计/日志目录 : %s", output_dir)



    stop_event = threading.Event()

    threads: list[threading.Thread] = []



    for i in range(1, thread_count + 1):

        t = threading.Thread(

            target=worker,

            args=(i, config, stop_event, stats_path, error_path, global_stats),

            name=f"Worker-{i:02d}",

            daemon=True,

        )

        threads.append(t)

        t.start()



    # 运行指定时长后，向所有线程发送停止信号

    try:

        logger.info("所有线程已运行，将在 %d 秒后停止（按 Ctrl+C 可提前终止）", total_runtime)

        time.sleep(total_runtime)

    except KeyboardInterrupt:

        logger.info("用户中断，正在停止线程...")



    logger.info("正在向所有线程发送停止信号...")

    stop_event.set()



    for t in threads:

        t.join(timeout=30)



    write_stats(stats_path, global_stats, label="final")

    logger.info("所有线程已停止，运行结束。")





if __name__ == "__main__":

    main()

