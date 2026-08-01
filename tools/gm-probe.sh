#!/usr/bin/env bash
# Why does Gismeteo answer 200 to curl and 403 to our app?
#
# No dependencies -- curl and python3 only, both present on macOS. Run it
# anywhere the failure reproduces:  bash gm-probe.sh
#
# The method is bisection, not guesswork. Start from the exact curl that works,
# add one thing at a time, and stop at the first row that flips to 403. That
# row is the answer. The tests after it separate the three possible layers:
# headers, HTTP version, and TLS fingerprint.

URL='https://www.gismeteo.ru/weather-yoshkar-ola-11975/'
UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'

row() {                       # row <label> <curl args...>
  local label="$1"; shift
  local out
  out=$(curl -sS -o /dev/null --max-time 20 \
        -w '%{http_code} http/%{http_version} %{size_download}b' "$@" "$URL" 2>&1) \
    || out="ERR ${out##*: }"
  printf '  %-40s %s\n' "$label" "$out"
}

echo
echo "=== 1. bisection: your working curl, then one addition per row ==="

A_LANG=(-H 'Accept-Language: ru-RU,ru;q=0.9')
A_HTML=(-H 'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8')
A_UIR=(-H 'Upgrade-Insecure-Requests: 1')
A_SECF=(-H 'Sec-Fetch-Dest: document' -H 'Sec-Fetch-Mode: navigate'
        -H 'Sec-Fetch-Site: none' -H 'Sec-Fetch-User: ?1')
A_CHUA=(-H 'sec-ch-ua: "Chromium";v="126", "Not(A:Brand";v="24", "Google Chrome";v="126"'
        -H 'sec-ch-ua-mobile: ?0' -H 'sec-ch-ua-platform: "macOS"')
A_CC=(-H 'Cache-Control: max-age=0')

row 'baseline (UA + Accept-Language)'      --compressed -A "$UA" "${A_LANG[@]}"
row '+ Accept: text/html'                  --compressed -A "$UA" "${A_LANG[@]}" "${A_HTML[@]}"
row '+ Upgrade-Insecure-Requests'          --compressed -A "$UA" "${A_LANG[@]}" "${A_HTML[@]}" "${A_UIR[@]}"
row '+ Sec-Fetch-*'                        --compressed -A "$UA" "${A_LANG[@]}" "${A_HTML[@]}" "${A_UIR[@]}" "${A_SECF[@]}"
row '+ sec-ch-ua'                          --compressed -A "$UA" "${A_LANG[@]}" "${A_HTML[@]}" "${A_UIR[@]}" "${A_SECF[@]}" "${A_CHUA[@]}"
row '+ Cache-Control (= our full set)'     --compressed -A "$UA" "${A_LANG[@]}" "${A_HTML[@]}" "${A_UIR[@]}" "${A_SECF[@]}" "${A_CHUA[@]}" "${A_CC[@]}"

echo
echo "=== 2. transport: same headers, different HTTP version ==="
row 'baseline, forced HTTP/1.1'            --compressed --http1.1 -A "$UA" "${A_LANG[@]}"
row 'baseline, forced HTTP/2'              --compressed --http2   -A "$UA" "${A_LANG[@]}"

echo
echo "=== 3. encoding ==="
row 'baseline, no --compressed'            -A "$UA" "${A_LANG[@]}"
row 'baseline, gzip/deflate only'          -A "$UA" "${A_LANG[@]}" -H 'Accept-Encoding: gzip, deflate'

echo
echo "=== 4. no user-agent at all (is it the UA being checked?) ==="
row 'no UA, no headers'                    --compressed

echo
echo "=== 5. TLS fingerprint: python vs curl, identical headers ==="
echo "     If curl is 200 here and both python rows are 403, no amount of"
echo "     header work will fix it -- the handshake itself is the tell."
python3 - "$URL" "$UA" <<'PY'
import sys, urllib.request, urllib.error

url, ua = sys.argv[1], sys.argv[2]
hdrs = {"User-Agent": ua, "Accept-Language": "ru-RU,ru;q=0.9"}

def show(label, fn):
    try:
        n = fn()
        print(f"  {label:<40} 200 {n}b")
    except urllib.error.HTTPError as e:
        print(f"  {label:<40} {e.code}")
    except Exception as e:
        print(f"  {label:<40} ERR {type(e).__name__}: {e}")

def stdlib():
    req = urllib.request.Request(url, headers=hdrs)
    with urllib.request.urlopen(req, timeout=20) as r:
        return len(r.read())

show("python urllib (stdlib ssl)", stdlib)

try:
    import httpx
    def h1():
        with httpx.Client(http2=False, follow_redirects=True, timeout=20) as c:
            return len(c.get(url, headers=hdrs).raise_for_status().text)
    def h2():
        with httpx.Client(http2=True, follow_redirects=True, timeout=20) as c:
            return len(c.get(url, headers=hdrs).raise_for_status().text)
    show("httpx HTTP/1.1", h1)
    show("httpx HTTP/2", h2)
except ImportError:
    print("  httpx not installed locally -- skipped (pip3 install httpx[http2])")
except Exception as e:
    print(f"  httpx setup failed: {e}")
PY

echo
echo "=== how to read this ==============================================="
echo "  A row in section 1 flips to 403  -> that header is the trigger."
echo "  Section 1 all 200, httpx 403     -> header ORDER or TLS, not content."
echo "  http/2 row 403, http/1.1 row 200 -> HTTP/2 fingerprinting."
echo "  curl all 200, python all 403     -> TLS fingerprint. Needs curl_cffi;"
echo "                                      headers cannot fix it."
echo "  everything 403 incl. plain curl  -> your IP is rate-limited. Wait."
echo
