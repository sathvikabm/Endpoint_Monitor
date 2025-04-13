"""
Endpoint Monitoring Script

This script monitors the health of multiple HTTP endpoints specified in a YAML configuration file.
It performs periodic health checks and logs availability statistics for each domain.

Usage:
    python monitor.py <config_file_path>

Configuration Format:
    The YAML file should contain a list of endpoint configurations, each with:
    - url: URL to monitor (required)
    - method: HTTP method to use (optional, defaults to GET)
    - headers: HTTP headers to include (optional)
    - body: Request body for POST/PUT requests (optional)
"""

import yaml
import time
import sys
import os
import logging
import datetime
import asyncio
import aiohttp
from collections import defaultdict
from urllib.parse import urlparse

def setup_logging(config_file):
    """
    Configure logging for the monitoring application.

    Args:
        config_file (str): Path to the configuration file.

    Returns:
        str: The path to the log file created.
    """
    os.makedirs('logs', exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    config_name = os.path.splitext(os.path.basename(config_file))[0]
    log_filename = f"logs/monitor_{config_name}_{timestamp}.log"

    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)

    logging.basicConfig(
        filename=log_filename,
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    logging.info(f"Logging initialized to file: {log_filename}")
    return log_filename

def load_config(file_path):
    """
    Load and validate the endpoint configuration from a YAML file.

    Args:
        file_path (str): Path to the YAML configuration file.

    Returns:
        list: A list of endpoint configuration dictionaries.

    Raises:
        ValueError: If the configuration format is invalid.
        SystemExit: If file cannot be loaded or parsed.
    """
    try:
        with open(file_path, 'r') as file:
            config = yaml.safe_load(file)
            if not isinstance(config, list):
                raise ValueError("Configuration must be a list of endpoints")
            for i, endpoint in enumerate(config):
                if "url" not in endpoint:
                    raise ValueError(f"Endpoint at index {i} is missing required 'url' field")
            logging.info(f"Loaded {len(config)} endpoints for monitoring")
            return config
    except (yaml.YAMLError, FileNotFoundError) as e:
        logging.error(f"Error loading configuration: {str(e)}")
        sys.exit(1)

async def check_health_async(endpoint, session, time_left):
    """
    Perform an asynchronous health check for a single endpoint.

    Args:
        endpoint (dict): Endpoint configuration dictionary.
        session (aiohttp.ClientSession): HTTP client session to use.
        time_left (float): Time remaining in the current monitoring cycle.

    Returns:
        tuple: (url, status) where status is one of "UP", "DOWN", or "SKIPPED".
    """
    url = endpoint["url"]
    method = endpoint.get("method", "GET").upper()
    headers = endpoint.get("headers", {})
    body = endpoint.get("body")

    if time_left < 0.6:
        logging.warning(f"Skipping endpoint {url} - insufficient time left in cycle")
        return url, "SKIPPED"

    logging.info(f"Checking endpoint: {method} {url}")

    try:
        start_time = time.time()
        timeout = aiohttp.ClientTimeout(total=0.5)

        if method == "GET":
            async with session.get(url, headers=headers, timeout=timeout) as response:
                status = response.status
        elif method == "POST":
            async with session.post(url, headers=headers, data=body, timeout=timeout) as response:
                status = response.status
        elif method == "PUT":
            async with session.put(url, headers=headers, data=body, timeout=timeout) as response:
                status = response.status
        elif method == "DELETE":
            async with session.delete(url, headers=headers, timeout=timeout) as response:
                status = response.status
        else:
            logging.warning(f"  Unsupported method: {method}, treating as DOWN")
            return url, "DOWN"

        elapsed = time.time() - start_time
        logging.info(f"  Response status code: {status}, time: {elapsed:.3f}s")

        if 200 <= status < 300 and elapsed <= 0.5:
            logging.info(f"  Endpoint status: UP")
            return url, "UP"
        else:
            reason = "Bad status code" if status < 200 or status >= 300 else "Response too slow"
            logging.warning(f"  Endpoint status: DOWN ({reason})")
            return url, "DOWN"

    except asyncio.TimeoutError:
        logging.warning(f"  Endpoint status: DOWN (Timeout after 0.5s)")
        return url, "DOWN"
    except aiohttp.ClientError as e:
        logging.warning(f"  Endpoint status: DOWN (Request error: {str(e)})")
        return url, "DOWN"
    except Exception as e:
        logging.error(f"  Endpoint status: DOWN (Unexpected error: {str(e)})")
        return url, "DOWN"

async def process_endpoints_batch(endpoints, cycle_start_time, cycle_duration=15, max_concurrent=7):
    """
    Process a batch of endpoint health checks concurrently with a concurrency limit.

    Args:
        endpoints (list): List of endpoint configurations.
        cycle_start_time (float): Timestamp when the cycle started.
        cycle_duration (int): Duration of each monitoring cycle in seconds.
        max_concurrent (int): Maximum number of concurrent checks.

    Returns:
        list: List of (url, status) tuples.
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    results = []

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=0)) as session:
        async def limited_check(endpoint):
            async with semaphore:
                current_time = time.time()
                elapsed = current_time - cycle_start_time
                time_left = cycle_duration - elapsed
                if time_left <= 0:
                    logging.warning("Cycle time limit reached, skipping remaining")
                    return endpoint["url"], "SKIPPED"
                return await check_health_async(endpoint, session, time_left)

        tasks = [limited_check(ep) for ep in endpoints]
        results = await asyncio.gather(*tasks)

    return results

async def monitor_endpoints(file_path):
    """
    Main monitoring function that continuously monitors endpoints.

    Args:
        file_path (str): Path to the YAML configuration file.
    """
    log_file = setup_logging(file_path)
    logging.info(f"Monitoring started, logs will be written to {log_file}")

    config = load_config(file_path)
    domain_stats = defaultdict(lambda: {"up": 0, "total": 0})
    skipped_stats = defaultdict(int)
    interval = 15
    cycle_count = 0

    while True:
        cycle_count += 1
        logging.info(f"\n---------------- Starting monitoring cycle #{cycle_count} ------------------")
        cycle_start = time.time()

        try:
            results = await process_endpoints_batch(config, cycle_start, interval)

            for url, status in results:
                parsed_url = urlparse(url)
                domain = parsed_url.netloc.split(':')[0]

                if status == "SKIPPED":
                    skipped_stats[domain] += 1
                else:
                    domain_stats[domain]["total"] += 1
                    if status == "UP":
                        domain_stats[domain]["up"] += 1

            check_elapsed = time.time() - cycle_start
            logging.info(f"Check completed in {check_elapsed:.2f} seconds")

            logging.info("Cumulative availability statistics:")
            for domain, stats in domain_stats.items():
                if stats["total"] > 0:
                    availability = int(100 * stats["up"] / stats["total"])
                    logging.info(f"{domain} has {availability}% availability percentage (checked {stats['total']} times)")

            if any(skipped_stats.values()):
                logging.warning("Skipped endpoint checks due to cycle time constraints:")
                for domain, count in skipped_stats.items():
                    if count > 0:
                        logging.warning(f"  {domain}: {count} checks skipped")

        except Exception as e:
            logging.error(f"Error during monitoring cycle: {str(e)}", exc_info=True)

        finally:
            elapsed = time.time() - cycle_start
            sleep_time = max(0, interval - elapsed)

            if sleep_time > 0:
                logging.info(f"Sleeping for {sleep_time:.2f} seconds until next cycle")
                await asyncio.sleep(sleep_time)
            else:
                logging.warning(f"WARNING: Cycle took longer than interval period! ({elapsed:.2f}s > {interval}s)")

if __name__ == "__main__":
    """
    Script entry point with command-line argument handling.
    """
    if len(sys.argv) != 2:
        print("Usage: python monitor.py <config_file_path>")
        sys.exit(1)

    config_file = sys.argv[1]

    try:
        asyncio.run(monitor_endpoints(config_file))
    except KeyboardInterrupt:
        logging.info("Monitoring stopped by user.")
    except Exception as e:
        logging.error(f"Unexpected error: {e}", exc_info=True)
        print(f"Failed to start monitoring: {e}")
