import urllib.request, time, sys
ip="192.168.1.100"
settings='''<?xml version="1.0" encoding="UTF-8"?>
<scan:ScanSettings xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05/03" xmlns:pwg="http://www.pwg.org/schemas/2010/12/sm">
  <pwg:Version>2.6</pwg:Version>
  <pwg:ScanRegions><pwg:ScanRegion><pwg:Height>3508</pwg:Height><pwg:Width>2550</pwg:Width><pwg:XOffset>0</pwg:XOffset><pwg:YOffset>0</pwg:YOffset></pwg:ScanRegion></pwg:ScanRegions>
  <pwg:InputSource>Platen</pwg:InputSource>
  <scan:ColorMode>RGB24</scan:ColorMode>
  <scan:XResolution>300</scan:XResolution>
  <scan:YResolution>300</scan:YResolution>
  <pwg:DocumentFormat>image/jpeg</pwg:DocumentFormat>
  <scan:Intent>Document</scan:Intent>
</scan:ScanSettings>'''.encode()
req=urllib.request.Request(f"http://{ip}/eSCL/ScanJobs", data=settings, method="POST")
req.add_header("Content-Type","text/xml")
try:
    with urllib.request.urlopen(req, timeout=20) as r:
        loc=r.headers.get("Location"); print("POST scanjobs:", r.status, "Location:", loc)
except urllib.error.HTTPError as e:
    print("HTTP", e.code, e.read()[:300]); sys.exit(1)
if not loc: sys.exit(1)
if loc.startswith("/"): url=f"http://{ip}{loc}/NextDocument"
else: url=loc+"/NextDocument"
for attempt in range(20):
    try:
        with urllib.request.urlopen(url, timeout=90) as r:
            data=r.read()
            ct=r.headers.get("Content-Type")
        print(f"got document: {len(data)} bytes  ct={ct}")
        open("scan_out.jpg","wb").write(data)
        break
    except urllib.error.HTTPError as e:
        if e.code==503:
            print(f"  not ready ({attempt}), sleeping"); time.sleep(2)
        else:
            print("HTTP", e.code, e.read()[:300]); break
