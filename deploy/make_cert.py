# -*- coding: utf-8 -*-
"""生成内网自签 HTTPS 证书（PEM）：python deploy/make_cert.py [域名或IP]
生成 data\certs\server.crt / server.key，然后设置：
    SLYS_SSL_CERT=data\certs\server.crt
    SLYS_SSL_KEY=data\certs\server.key
重启平台即 https 直出。浏览器首次访问需信任该证书（或导入 server.crt 到受信任的根证书颁发机构）。
依赖：pip install cryptography"""
import ipaddress
import os
import sys
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8")
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
name = sys.argv[1] if len(sys.argv) > 1 else "localhost"
out = os.path.join(BASE, "data", "certs")
os.makedirs(out, exist_ok=True)

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
except ImportError:
    print("需要 cryptography 库：pip install cryptography")
    sys.exit(1)

key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
alt = [x509.DNSName(name)]
try:
    alt.append(x509.IPAddress(ipaddress.ip_address(name)))
except ValueError:
    pass
alt.append(x509.DNSName("localhost"))
alt.append(x509.IPAddress(ipaddress.ip_address("127.0.0.1")))
cert = (x509.CertificateBuilder()
        .subject_name(subject).issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now() - timedelta(days=1))
        .not_valid_after(datetime.now() + timedelta(days=3650))
        .add_extension(x509.SubjectAlternativeName(alt), critical=False)
        .sign(key, hashes.SHA256()))

with open(os.path.join(out, "server.key"), "wb") as f:
    f.write(key.private_bytes(serialization.Encoding.PEM,
                              serialization.PrivateFormat.TraditionalOpenSSL,
                              serialization.NoEncryption()))
with open(os.path.join(out, "server.crt"), "wb") as f:
    f.write(cert.public_bytes(serialization.Encoding.PEM))
print("已生成：")
print(" ", os.path.join(out, "server.crt"))
print(" ", os.path.join(out, "server.key"))
print("启用：SLYS_SSL_CERT=...\\server.crt  SLYS_SSL_KEY=...\\server.key 后重启平台")
print("提示：内网机器把 server.crt 导入“受信任的根证书颁发机构”即无告警访问")
