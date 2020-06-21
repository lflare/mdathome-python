# MangaDex@Home... in Python!
_An unofficial client-rewrite by @lflare!_

## Disclaimer
No support will be given with this unofficial rewrite. Feature recommendations are not welcomed, but pull requests with new features are. This fork was created entirely out of goodwill and boredom, and if the creator so decides, will not receive future support at any point in time.

## Installation
In order to get this client working, you will need the basic client requirements stipulated by the official MDClient **and additionally, Python 3.8 and PIP**. With requirements fulfilled, you will need to install the libraries that this rewrite uses

```bash
root@mdathome:~/mdathome$ pip3 install -r requirements.txt 
Collecting sanic
  Downloading sanic-20.3.0-py3-none-any.whl (73 kB)
     |████████████████████████████████| 73 kB 2.5 MB/s 
[...snip...]
Collecting h11<0.10,>=0.8
  Downloading h11-0.9.0-py2.py3-none-any.whl (53 kB)
     |████████████████████████████████| 53 kB 5.2 MB/s 
Collecting hpack<4,>=3.0
  Downloading hpack-3.0.0-py2.py3-none-any.whl (38 kB)
Collecting hyperframe<6,>=5.2.0
  Downloading hyperframe-5.2.0-py2.py3-none-any.whl (12 kB)
ERROR: sanic 20.3.0 has requirement httpx==0.11.1, but you'll have httpx 0.13.3 which is incompatible.
Installing collected packages: websockets, idna, rfc3986, hpack, hyperframe, h2, sniffio, h11, httpcore, hstspreload, chardet, certifi, httpx, multidict, httptools, ujson, uvloop, aiofiles, sanic, diskcache
Successfully installed aiofiles-0.5.0 certifi-2020.6.20 chardet-3.0.4 diskcache-4.1.0 h11-0.9.0 h2-3.2.0 hpack-3.0.0 hstspreload-2020.6.16 httpcore-0.9.1 httptools-0.1.1 httpx-0.13.3 hyperframe-5.2.0 idna-2.9 multidict-4.7.6 rfc3986-1.4.0 sanic-20.3.0 sniffio-1.1.0 ujson-3.0.0 uvloop-0.14.0 websockets-8.1
```

## Configuration
As with the official client, this client reads the same JSON, with an additional option to modify actual reported disk size.

```json
{
    "client_secret": "thisisafakesecretcreatedbythebigmango",
    "client_port": 44300,
    "threads": 8,
    "max_cache_size_in_mebibytes": 80000,
    "max_reported_size_in_mebibytes": 80000,
    "max_kilobits_per_second": 100000
}
```

### `client_secret`
Self-explanatory, this should be obtained from the [MangaDex@Home page](https://mangadex.org/md_at_home).

### `client_port` - Recommended `44300`
Self-explanatory, runs the client on the port you specify

### `threads` - Recommended min. `4`
This setting, like the official MDClient, specifies the amount of threads to be used in the underlying web server. However, this client is coded asynchronously, thus the amount of `threads` needed for the same performance, is much lower.

### `max_cache_size_in_mebibytes`
This is the max cache size in mebibytes stored on your disk, do not exceed what is actually possibly storable on your drive.

### `max_reported_size_in_mebibytes`
This is the cache size reported to the backend server. This may cause your server to get more shards, but due to the nature of how this will work, setting this variable too high will cause too much file "swapping". It is **highly** recommended that you set this variable the same as `max_cache_size_in_mebibytes`.

### `max_kilobits_per_second`
This setting currently only reports to the backend, and does not actually limit the speed client side.

## License
[AGPLv3](https://choosealicense.com/licenses/agpl-3.0/)
