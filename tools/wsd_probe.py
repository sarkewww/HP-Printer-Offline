import socket, struct, time, uuid
# WS-Discovery probe
msg = '''<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing" xmlns:wsd="http://schemas.xmlsoap.org/ws/2005/04/discovery" xmlns:wsdp="http://schemas.xmlsoap.org/ws/2006/02/devprof">
<soap:Header>
<wsa:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</wsa:To>
<wsa:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</wsa:Action>
<wsa:MessageID>urn:uuid:%s</wsa:MessageID>
</soap:Header>
<soap:Body><wsd:Probe/></soap:Body></soap:Envelope>''' % uuid.uuid4()
data=msg.encode()
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM,socket.IPPROTO_UDP)
s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
s.setsockopt(socket.IPPROTO_IP,socket.IP_MULTICAST_IF,socket.inet_aton("192.168.1.100"))
s.setsockopt(socket.IPPROTO_IP,socket.IP_MULTICAST_TTL,2)
s.bind(("192.168.1.100",0))
s.settimeout(1.0)
s.sendto(data,("239.255.255.250",3702))
t=time.time(); n=0
while time.time()-t<8:
    try: d,addr=s.recvfrom(9000)
    except socket.timeout: continue
    n+=1
    print("="*60); print("FROM",addr); print(d.decode("utf-8","replace")[:2500])
print("responses:",n)
