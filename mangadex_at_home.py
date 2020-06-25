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
limits = httpx.PoolLimits(max_keepalive=100, max_connections=1000)
timeout = httpx.Timeout(300)
client = httpx.AsyncClient(verify=False, pool_limits=limits, timeout=timeout)

##
# Cache Async Libraries
##
async def set_async(key, val):
    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(None, cache.set, key, val)
    result = await future
    return result

async def get_async(key):
    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(None, cache.get, key)
    result = await future
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
        logger.info(f"Request for {request.ctx.sanitized_url} - {request.ip} - {request.ctx.referer} completed in {time_taken:.3f}ms")
        response.headers["X-Time-Taken"] = f"{int(time_taken)}"

    # GARBAGE COLLECT
    gc.collect()

##
# MDnet Constants
##
default_server_headers = {
    "Access-Control-Allow-Origin": "https://mangadex.org",
    "Access-Control-Expose-Headers": "*",
    "Cache-Control": "public, max-age=1209600",
    "Server": "Mangadex@Home Node 1.0.0 (13)",
    "Timing-Allow-Origin": "https://mangadex.org",
    "X-Content-Type-Options": "nosniff"
}

default_ping_headers = {
    "Content-Type": "application/json; charset=utf-8",
    "Connection": "Keep-Alive",
    "User-Agent": "Apache-HttpClient/4.5.12 (Java/11.0.7)",
    "Accept-Encoding": "gzip,deflate",
}

##
# MDnet Utility Functions
##
def get_ping_params(app):
    # Read settings.json in the event of an updated speed
    with open("settings.json") as file:
        configuration = json.loads(file.read())

    return {
        "secret": configuration["client_secret"],
        "port": configuration["client_port"],
        "disk_space": int(configuration["max_reported_size_in_mebibytes"] * 1024 * 1024),
        "network_speed": int(configuration["max_kilobits_per_second"] * 1000 / 8),
        "build_version": 13,
        "tls_created_at": app.tls_created_at
    }

def handle_ping(app, server_settings):
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

def server_ping(app):
    # Handler for sync ping
    json = get_ping_params(app)
    if json["tls_created_at"] is None: json.pop("tls_created_at")
    logger.info(f"Pinging control server! - {json}")
    r = httpx.post(f"{app.api_server}/ping", verify=False, json=json, headers=default_ping_headers)
    if r.status_code == httpx.codes.OK:
        return handle_ping(app, r.json())
    else:
        logger.error(f"Ping errored out! - {r.text}")

def server_ping_thread(app):
    time.sleep(45)
    while cache.get("running") == True:
        # Run ping function
        server_ping(app)

        # Wait till next ping
        time.sleep(45)

@app.listener('before_server_stop')
async def server_stop(app, loop):
    # Start graceful shutdown
    logger.info("Starting graceful shutdown!")
    await set_async("running", False)

    # Shutdown client on backend
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
@app.route("/<request_token>/<image_type>/<chapter_hash>/<image_name>/<extra_one>/<extra_two>/<extra_three>/<extra_four>")
async def handle_request(request, image_type, chapter_hash, image_name, request_token=None, extra_one=None, extra_two=None, extra_three=None, extra_four=None):
    # Validate request
    if image_type not in ["data", "data-saver"]:
        return response.empty(status=400)
    if not re.match(r"[0-9a-f]{32}", chapter_hash):
        return response.empty(status=400)
    if not re.match(r"[a-z0-9]{1,4}\.(jpg|jpeg|png|gif)", image_name.lower()):
        return response.empty(status=400)

    # Get visitor origin
    request.ctx.referer = None
    if "Referer" in request.headers:
        match = re.findall("https://mangadex.org/chapter/[0-9]+", request.headers["Referer"])
        if len(match) == 1:
            request.ctx.referer = match[0]

    # Update last request
    request.ctx.sanitized_url = f"/{image_type}/{chapter_hash}/{image_name}"
    logger.info(f"Request for {request.ctx.sanitized_url} - {request.ip} - {request.ctx.referer} received")
    app.last_request = time.time()

    # Check if If-Modified-Since exists
    if "If-Modified-Since" in request.headers:
        logger.info(f"Request for {request.ctx.sanitized_url} - {request.ip} - {request.ctx.referer} cached by browser")
        return response.empty(status=httpx.codes.not_modified)

    # Prepare default headers
    headers = default_server_headers.copy()
    headers["X-Uri"] = request.ctx.sanitized_url

    # Compute unique image hash
    request_hash = hashlib.sha512(f"{image_type}{chapter_hash}{image_name}".encode()).hexdigest()

    # Prepare upstream image URL
    image_url = f"{app.image_server}/{image_type}/{chapter_hash}/{image_name}"

    # Check if inside cache
    if request_hash in cache:
        # Log cache hit
        logger.info(f"Request for {request.ctx.sanitized_url} - {request.ip} - {request.ctx.referer} hit cache")

        # Update cache header
        headers["X-Cache"] = "HIT"

        # Retrieve image from cache
        image, content_type, content_length, last_modified = await get_async(request_hash)

        # Update headers
        headers["Content-Type"] = content_type
        headers["Content-Length"] = content_length if content_length is not None else len(image)
        if last_modified is not None: headers["Last-Modified"] = last_modified

        # Return image
        return response.raw(image, headers=headers)
    else:
        # Log cache miss
        logger.info(f"Request for {request.ctx.sanitized_url} - {request.ip} - {request.ctx.referer} missed cache")

        # Update cache header
        headers["X-Cache"] = "MISS"

        # Prepare upstream request
        req = client.build_request("GET", image_url)
        r = await client.send(req, stream=True)

        # Check validity of response
        try:
            # Check response status code
            if r.status_code != httpx.codes.OK: raise Exception

            # Update headers
            content_type = content_length = last_modified = None
            if "Content-Type" in r.headers: headers["Content-Type"] = content_type = r.headers["Content-Type"]
            if "Content-Length" in r.headers: headers["Content-Length"] = content_length = r.headers["Content-Length"]
            if "Last-Modified" in r.headers: headers["Last-Modified"] = last_modified = r.headers["Last-Modified"]
        except:
            # Log error
            logger.error(f"Request for {request.ctx.sanitized_url} - {request.ip} - {request.ctx.referer} failed")

            # GARBAGE COLLECT
            await r.aclose()
            gc.collect()

            # Redirect to upstream
            return response.redirect(image_url)

        # Image streaming handler
        async def stream_image(response):
            try:
                # Stream image
                image = b""
                async for chunk in r.aiter_raw():
                    # Send chunk to visitor
                    await response.write(chunk)
                    image += chunk

                # Save into cache
                await set_async(request_hash, (image, content_type, content_length, last_modified))
            except:
                # Log error
                logger.error(f"Request for {request.ctx.sanitized_url} - {request.ip} - {request.ctx.referer} failed")
            finally:
                # GARBAGE COLLECT
                await r.aclose()
                gc.collect()

        # Return image streaming handler
        return response.stream(stream_image, headers=headers)

# Start initial ping
server_ping(app)

# Start pinging thread
ping_thread = threading.Thread(target=server_ping_thread, args=(app,))
ping_thread.daemon = True
ping_thread.start()

if __name__ == "__main__":
    # Run webserver
    app.run(host="0.0.0.0", port=configuration["client_port"], workers=int(configuration["threads"]),
            access_log=False, ssl={'cert': "./server.crt", 'key': "./server.key"})
