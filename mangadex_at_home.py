#! /usr/bin/env python3.8
##
from diskcache import Cache
from sanic import Sanic, response, log
from sanic.log import logger
import asyncio
import gc
import hashlib
import httpx
import json
import os
import random
import re
import ssl
import threading
import time

# Load configuration from settings.json
with open("settings.json") as file:
    configuration = json.loads(file.read())
PING_SLEEP = 45

## Cache
GIBIBYTE = 2**30
MEBIBYTE = 2**20
cache = Cache("./cache", size_limit=configuration["max_cache_size_in_mebibytes"] * MEBIBYTE)

##
# Sanic configuration
##
LOGGING = log.LOGGING_CONFIG_DEFAULTS
LOGGING["handlers"]["file"] = {
    'class': 'logging.FileHandler',
    'formatter': 'generic',
    'filename': "log/latest.log",
    'mode': 'a'
}
LOGGING["handlers"]["error_file"] = {
    'class': 'logging.FileHandler',
    'formatter': 'access',
    'filename': "log/error.log",
    'mode': 'a'
}
LOGGING["handlers"]["access_file"] = {
    'class': 'logging.FileHandler',
    'formatter': 'access',
    'filename': "log/access.log",
    'mode': 'a'
}
LOGGING["loggers"]["sanic.root"]["handlers"].append("file")
LOGGING["loggers"]["sanic.error"]["handlers"].append("error_file")
LOGGING["loggers"]["sanic.access"]["handlers"].append("access_file")
LOGGING["formatters"]["generic"]["datefmt"] = "%Y-%m-%dT%H:%M:%S%z"
LOGGING["formatters"]["access"]["datefmt"] = "%Y-%m-%dT%H:%M:%S%z"

# Initialize Sanic
app = Sanic("MDClient rewritten in Python!", log_config=LOGGING)
app.config.KEEP_ALIVE_TIMEOUT = 60
app.tls_created_at = None

# Initialise httpx
client = httpx.AsyncClient(verify=False)

##
# Cache Async Libraries
##
async def set_async(key, val):
    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(None, cache.set, key, val)
    result = await future
    gc.collect()
    return result

async def get_async(key):
    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(None, cache.get, key)
    result = await future
    gc.collect()
    return result

##
# Utility Constants
##
cache.set("running", True)
app.last_request = time.time()
app.image_server = "https://s2.mangadex.org"
app.api_server = "https://api.mangadex.network"

##
# Sanic Utility Functions
##
@app.middleware('request')
async def add_start_time(request):
    request.ctx.start_time = time.time()

@app.middleware('response')
async def add_spent_time(request, response):
    if hasattr(request.ctx, "sanitized_url"):
        time_taken = (time.time() - request.ctx.start_time) * 1000
        logger.info(f"Request for {request.ctx.sanitized_url} completed in {time_taken:.3f}ms")
        response.headers["X-Time-Taken"] = f"{int(time_taken)}"

    # Call garbage collector
    gc.collect()

##
# MDnet Utility Functions
##
def get_ping_headers():
    return {
        "content-type": "application/json; charset=utf-8",
        "Connection": "Keep-Alive",
        "User-Agent": "Apache-HttpClient/4.5.12 (Java/11.0.7)",
        "Accept-Encoding": "gzip,deflate",
    }

def get_ping_params(app):
    return {
        "secret": configuration["client_secret"],
        "port": configuration["client_port"],
        "disk_space": int(configuration["max_reported_size_in_mebibytes"] * 1024 * 1024),
        "network_speed": int(configuration["max_kilobits_per_second"] * 1000 / 8),
        "build_version": 10,
        "tls_created_at": app.tls_created_at
    }

def handle_ping(app, r):
    if r.status_code == httpx.codes.OK:
        # Parse server settings
        server_settings = r.json()

        # Write Image server
        app.image_server = server_settings["image_server"]

        # Handle SSL/TLS certificates
        if "tls" in server_settings:
            tls = server_settings["tls"]
            if tls is not None:
                app.tls_created_at = tls["created_at"]

                # Write certificates to file
                with open("server.crt", "w") as file:
                    file.write(tls["certificate"])
                    server_settings["tls"].pop("certificate")
                with open("server.key", "w") as file:
                    file.write(tls["private_key"])
                    server_settings["tls"].pop("private_key")

        # Log
        logger.info(f"Server settings received! - {server_settings}")
    else:
        logger.error(f"Ping errored out! - {r.text}")

def server_ping(app):
    # Handler for sync ping
    json = get_ping_params(app)
    if json["tls_created_at"] is None: json.pop("tls_created_at")
    logger.info(f"Pinging control server! - {json}")
    r = httpx.post(f"{app.api_server}/ping", verify=False, json=json, headers=get_ping_headers())
    return handle_ping(app, r)

def server_ping_thread(app):
    time.sleep(45)
    while cache.get("running") == True:
        server_ping(app)
        time.sleep(45)

async def download_image(image_url):
    for attempt in range(3):
        r = await client.get(image_url)
        if r.status_code == httpx.codes.OK:
            content_length = last_modified = None
            if "Content-Length" in r.headers:
                content_length = r.headers["Content-Length"]
            if "Last-Modified" in r.headers:
                last_modified = r.headers["Last-Modified"]

            gc.collect()
            return r.read(), r.headers['Content-Type'], content_length, last_modified
    gc.collect()
    return r.status_code

@app.listener('before_server_stop')
async def server_stop(app, loop):
    logger.info("Starting graceful shutdown!")
    await set_async("running", False)
    r = await client.post(f"{app.api_server}/stop", json={"secret": get_ping_params(app)["secret"]})
    # Wait till last request is more than 5 seconds old
    time_diff = time.time() - app.last_request
    while time_diff < 5:
        logger.info(f"Last request was {time_diff:.2f} seconds ago...")
        time_diff = time.time() - app.last_request
        await asyncio.sleep(1)

##
# MDnet HTTP Handler
##
@app.route("/<image_type>/<chapter_hash>/<image_name>")
@app.route("/<request_token>/<image_type>/<chapter_hash>/<image_name>")
async def handle_request(request, image_type, chapter_hash, image_name, request_token=None):
    # Validate request
    if image_type not in ["data", "data-saver"]:
        return response.empty(status=400)
    if not re.match(r"[0-9a-f]{32}", chapter_hash):
        return response.empty(status=400)
    if not re.match(r"[a-z0-9]{1,4}\.(jpg|png|gif)", image_name.lower()):
        return response.empty(status=400)

    # Update last request
    request.ctx.sanitized_url = f"/{image_type}/{chapter_hash}/{image_name}"
    logger.info(f"Request for {request.ctx.sanitized_url} received")
    app.last_request = time.time()

    # Prepare headers
    headers = {
        "Access-Control-Allow-Origin": "https://mangadex.org",
        "Access-Control-Expose-Headers": "*",
        "Cache-Control": "public, max-age=1209600",
        "Server": "Mangadex@Home Node 1.0 (10)",
        "Timing-Allow-Origin": "https://mangadex.org",
        "X-Content-Type-Options": "nosniff"

    }

    # Check if If-Modified-Since exists
    if "If-Modified-Since" in request.headers:
        logger.info(f"Request for {request.ctx.sanitized_url} cached by browser")
        return response.empty(status=httpx.codes.not_modified)

    # Compute unique image hash
    request_hash = hashlib.sha512(f"{image_type}{chapter_hash}{image_name}".encode()).hexdigest()

    # Check if inside cache
    image = None
    if request_hash in cache:
        logger.info(f"Request for {request.ctx.sanitized_url} hit cache")

        # Retrieve image from cache
        image = await get_async(request_hash)

        # Update headers
        headers["X-Cache"] = "HIT"
    else:
        logger.info(f"Request for {request.ctx.sanitized_url} missed cache")

        # Attempt to retrieve image from upstream
        image_url = f"{app.image_server}/{image_type}/{chapter_hash}/{image_name}"
        image = await download_image(image_url)

        # If upstream return error, log and redirect to upstream server
        if type(image) == int:
            logger.error(f"Request for {request.ctx.sanitized_url} failed")
            return response.redirect(image_url)

        # Save image into cache
        await set_async(request_hash, image)

        # Update headers
        headers["X-Cache"] = "MISS"

    # Update headers
    headers["Content-Type"] = image[1]
    headers["Content-Length"] = image[2] if image[2] is not None else len(image[0])
    if image[3] is not None: headers["Last-Modified"] = image[3]
    headers["X-Uri"] = request.ctx.sanitized_url

    # Collect garbage
    gc.collect()

    # Return image
    return response.raw(image[0], headers=headers)

if __name__ == "__main__":
    # Start initial ping
    server_ping(app)

    # Start pinging thread
    ping_thread = threading.Thread(target=server_ping_thread, args=(app,))
    ping_thread.daemon = True
    ping_thread.start()

    # Run webserver
    app.run(host="0.0.0.0", port=configuration["client_port"], workers=int(configuration["threads"]),
            access_log=False, ssl={'cert': "./server.crt", 'key': "./server.key"})
