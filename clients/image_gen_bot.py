"""

多线程 GPT 图像生成机器人

通过 OpenAI 兼容 API 使用 gpt-image-2 模型生成图像。

"""



import json

import os

import random

import threading

import time

import base64

import logging

from datetime import datetime

from pathlib import Path



import requests



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



def generate_image(base_url: str, api_key: str, model: str, prompt: str,

                   size: str, quality: str) -> tuple[bytes | None, float]:

    """

    调用 OpenAI 兼容的图像生成接口。

    返回 (图像字节数据, 响应耗时秒数)；失败时图像数据为 None。

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

        resp = requests.post(url, headers=headers, json=payload, timeout=300)

        resp.raise_for_status()

        data = resp.json()

        b64 = data["data"][0]["b64_json"]

        return base64.b64decode(b64), time.time() - start

    except requests.exceptions.HTTPError as e:

        logger.error("HTTP 错误: %s – %s", e, resp.text[:300] if resp else "")

    except requests.exceptions.RequestException as e:

        logger.error("请求错误: %s", e)

    except (KeyError, IndexError, ValueError) as e:

        logger.error("响应解析错误: %s", e)

    return None, time.time() - start



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



# ---------------------------------------------------------------------------

# 工作线程

# ---------------------------------------------------------------------------



def worker(thread_id: int, config: dict, stop_event: threading.Event,

           output_dir: Path, stats_path: Path, global_stats: GlobalStats):

    api_cfg = config["api"]

    rt_cfg = config["runtime"]

    prompts: list[str] = config["prompts"]



    logger.info("线程-%02d 已启动", thread_id)



    while not stop_event.is_set():

        prompt = random.choice(prompts)

        logger.info("线程-%02d | 提示词: %s", thread_id, prompt[:60])



        img_bytes, response_time = generate_image(

            base_url=api_cfg["base_url"],

            api_key=api_cfg["api_key"],

            model=api_cfg["model"],

            prompt=prompt,

            size=api_cfg["image_size"],

            quality=api_cfg["image_quality"],

        )



        if img_bytes:

            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

            img_path = output_dir / f"{ts}_t{thread_id:02d}.png"

            img_path.write_bytes(img_bytes)

            logger.info("线程-%02d | 已保存图像: %s (%d 字节, %.2f 秒)", thread_id, img_path.name, len(img_bytes), response_time)

            hit_milestone = global_stats.record_call(True, response_time)

        else:

            logger.warning("线程-%02d | 图像生成失败 (%.2f 秒)", thread_id, response_time)

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

    global_stats = GlobalStats()



    logger.info("正在启动图像生成机器人")

    logger.info("  线程数        : %d", thread_count)

    logger.info("  总运行时间    : %d 秒", total_runtime)

    logger.info("  调用间隔      : %s 秒", rt_cfg["call_interval_seconds"])

    logger.info("  模型          : %s", config["api"]["model"])

    logger.info("  已加载提示词  : %d 条", len(config["prompts"]))

    logger.info("  输出目录      : %s", output_dir)



    stop_event = threading.Event()

    threads: list[threading.Thread] = []



    for i in range(1, thread_count + 1):

        t = threading.Thread(

            target=worker,

            args=(i, config, stop_event, output_dir, stats_path, global_stats),

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

