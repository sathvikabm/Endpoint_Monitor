# Endpoint_Monitor
This script monitors the health of multiple HTTPS endpoints asynchronously using Python. It logs response times and availability percentages across monitoring cycles and stores them with detailed logs in a timestamped file.

## Requirements:
Python (>=3.6)
```pip install aiohttp pyyaml ```

## How to Run:
``` python monitor.py <config_file_path>```
```Cltr+C to terminate```

## Configuration Format:
Check out ``` sample.yaml```

## How it works
### a) Logging Setup
setup_logging(config_file): Creates a logs/ folder and initializes a new log file with a timestamp and the config file name.
Logs are written to: ```logs/monitor_<config_name>_<timestamp>.log```

### b) Loading Config
load_config(): Parses the YAML file and validates each endpoint (e.g., missing URLs are flagged early).

### c) Cycle Timing & Concurrency
- Monitor runs in 15-second cycles(If it processes all endpoints before 15sec it sleeps for the remaining time)
- A Semaphore is used to control concurrency (max_concurrent=7 by default), which ensures that all endpoints are not hit at once and avoids event loop saturation.

### d) Endpoint Monitoring
- check_health_async(): Sends HTTP requests using aiohttp based on the method type (GET, POST, PUT, DELETE).
- It checks:
---Response time (must be ≤ 0.5s),
---Response status (must be between 200 and 299),
---And skips the check if not enough time is left in the cycle.

### e) Concurrency Management
- process_endpoints_batch(): Uses asyncio.gather() to fire off concurrent checks, along with a Semaphore.

### f) Statistics Tracking
- monitor_endpoints(): Aggregates and logs per-domain availability percentages after every cycle.
- Skipped checks and slow endpoints are also logged and accounted for.

## The initial version ran all endpoint checks sequentially, which was:
1) Too slow for a large number of endpoints
2) Prone to wasting time if early checks were slow or blocked.

## Improvement:
1) Introduced async I/O using aiohttp for faster request handling.
2) Used asyncio.Semaphore to throttle concurrency and avoid overloading the event loop or target servers.
3) Used asyncio.gather() to fire off checks concurrently, improving speed without losing control.
4) Passed time_left to check_health_async to skip checks near the end of a cycle.

