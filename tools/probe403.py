"""Why does a source answer 200 to curl and 403 to us?

Runs *inside the built image*, using the app's own headers, so the only
difference from production is that you are watching. Three header sets against
HTTP/1.1 and HTTP/2.

    docker run --rm -i -v "$PWD/tools/probe403.py:/probe.py:ro" \
      ghcr.io/mureev/cm-weather:latest python /probe.py

If every row fails and plain curl succeeds from the same machine, it is the TLS
fingerprint. If every row fails *and* curl fails, it is the IP -- which is what
happened with Gismeteo. See tools/gm-probe.sh for the no-dependency version
that bisects that too.
"""

import httpx

URL = "https://www.gismeteo.ru/weather-yoshkar-ola-11975/"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

CURLISH = {"User-Agent": UA, "Accept-Language": "ru-RU,ru;q=0.9", "Accept": "*/*"}
APP = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Upgrade-Insecure-Requests": "1",
}
CHROME = dict(APP, **{
    "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none", "Sec-Fetch-User": "?1",
    "sec-ch-ua": '"Chromium";v="126", "Not(A:Brand";v="24", "Google Chrome";v="126"',
    "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": '"macOS"',
    "Cache-Control": "max-age=0",
})

for hname, hdrs in (("curlish", CURLISH), ("app", APP), ("chrome", CHROME)):
    for pname, h2 in (("h1", False), ("h2", True)):
        try:
            with httpx.Client(http2=h2, follow_redirects=True, timeout=20) as c:
                r = c.get(URL, headers=hdrs)
                print(f"  {hname:8} {pname}  ->  {r.status_code}  "
                      f"{len(r.text):>7} bytes  proto={r.http_version}")
        except Exception as e:
            print(f"  {hname:8} {pname}  ->  EXC {type(e).__name__}: {e}")
