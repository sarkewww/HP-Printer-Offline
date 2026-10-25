import urllib.request, urllib.error, re, time
ip="192.168.1.100"
def get(u):
    with urllib.request.urlopen(u, timeout=10) as r: return r.read().decode("utf-8","replace")
st=get(f"http://{ip}/eSCL/ScannerStatus")
jobs=re.findall(r"<pwg:JobUri>([^<]+)</pwg:JobUri>", st)
print("jobs:", jobs)
for j in jobs:
    url=f"http://{ip}{j}"
    try:
        req=urllib.request.Request(url, method="DELETE")
        with urllib.request.urlopen(req, timeout=10) as r:
            print("DELETE", j, "->", r.status)
    except urllib.error.HTTPError as e:
        print("DELETE", j, "->", e.code)
    except Exception as e:
        print("DELETE", j, "-> EXC", e)
time.sleep(2)
st=get(f"http://{ip}/eSCL/ScannerStatus")
print("state:", re.findall(r"<pwg:State>([^<]+)</pwg:State>", st))
