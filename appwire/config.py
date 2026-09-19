"""Strict, non-executable subset of wg-quick configuration."""
import base64
import ipaddress
import re
from dataclasses import dataclass

MAX_CONFIG = 32768
NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}\Z")


def profile_name(value):
    if not isinstance(value, str) or not NAME.fullmatch(value):
        raise ValueError("Profile name: 1–32 lowercase letters, numbers, _ or -")
    return value


def key(value):
    try:
        if len(base64.b64decode(value, validate=True)) == 32:
            return value
    except Exception:
        pass
    raise ValueError("Invalid WireGuard key")


def number(value, low, high):
    if not value.isascii() or not value.isdecimal() or not low <= int(value) <= high:
        raise ValueError("Numeric setting out of range")
    return str(int(value))


def endpoint(value):
    match = re.fullmatch(r"(?:\[([0-9a-fA-F:]+)\]|([A-Za-z0-9.-]+)):(\d{1,5})", value)
    if not match:
        raise ValueError("Endpoint must be hostname:port, IPv4:port or [IPv6]:port")
    if match[1]:
        ipaddress.IPv6Address(match[1])
    elif len(match[2]) > 253 or any(not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", x) for x in match[2].split('.')):
        raise ValueError("Invalid endpoint hostname")
    number(match[3], 1, 65535)
    return value


@dataclass
class Config:
    interface: dict
    peers: list
    addresses: list
    dns: list
    searches: list
    mtu: int

    def native(self):
        sections = [("Interface", self.interface)] + [("Peer", p) for p in self.peers]
        return '\n'.join('[' + name + ']\n' + '\n'.join(f'{k} = {v}' for k, v in values.items()) for name, values in sections) + '\n'

    def resolver(self):
        return ''.join(f'nameserver {x}\n' for x in self.dns) + (('search ' + ' '.join(self.searches) + '\n') if self.searches else '') + 'options timeout:2 attempts:2\n'

    @property
    def routes(self):
        return sorted({x.strip() for p in self.peers for x in p['AllowedIPs'].split(',')})


def parse(text):
    if not isinstance(text, str) or len(text.encode()) > MAX_CONFIG or '\x00' in text:
        raise ValueError("Invalid or oversized configuration")
    interface, peers, current = {}, [], None
    for line in text.splitlines():
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        if line == '[Interface]':
            if current is not None:
                raise ValueError("Exactly one Interface section must come first")
            current = interface
        elif line == '[Peer]':
            if current is None or len(peers) >= 16:
                raise ValueError("Interface must precede at most 16 peers")
            current = {}
            peers.append(current)
        else:
            if current is None or '=' not in line:
                raise ValueError("Invalid configuration line")
            k, v = [s.strip() for s in line.split('=', 1)]
            allowed = {'PrivateKey', 'Address', 'DNS', 'MTU', 'ListenPort'} if current is interface else {'PublicKey', 'PresharedKey', 'Endpoint', 'AllowedIPs', 'PersistentKeepalive'}
            if k not in allowed or k in current or not v:
                raise ValueError("Unsupported, repeated or empty setting: " + k[:40])
            current[k] = v
    if not {'PrivateKey', 'Address', 'DNS'} <= interface.keys() or not peers:
        raise ValueError("Require Interface PrivateKey, Address, DNS and at least one Peer")
    key(interface['PrivateKey'])
    addresses = [str(ipaddress.ip_interface(x.strip())) for x in interface.pop('Address').split(',')]
    if len(addresses) > 16:
        raise ValueError("Too many addresses")
    dns, searches = [], []
    for x in interface.pop('DNS').split(','):
        x = x.strip()
        try:
            addr = ipaddress.ip_address(x)
            if addr.is_loopback or addr.is_unspecified or addr.is_multicast or addr.is_link_local:
                raise ValueError("DNS must be reachable through the tunnel")
            dns.append(str(addr))
        except ValueError:
            if re.fullmatch(r'(?=.{1,253}\Z)[a-zA-Z][a-zA-Z0-9.-]*', x):
                searches.append(x)
            else:
                raise ValueError("Invalid DNS address or search domain") from None
    if not dns or len(dns) > 3 or len(searches) > 6:
        raise ValueError("Require 1–3 numeric tunnel DNS servers and at most 6 search domains")
    mtu = int(number(interface.pop('MTU', '1420'), 1280, 9000))
    if 'ListenPort' in interface:
        interface['ListenPort'] = number(interface['ListenPort'], 0, 65535)
    public_keys, all_routes = set(), []
    for p in peers:
        if not {'PublicKey', 'AllowedIPs', 'Endpoint'} <= p.keys():
            raise ValueError("Each peer requires PublicKey, AllowedIPs and Endpoint")
        key(p['PublicKey'])
        if p['PublicKey'] in public_keys:
            raise ValueError("Duplicate peer public key")
        public_keys.add(p['PublicKey'])
        if 'PresharedKey' in p:
            key(p['PresharedKey'])
        endpoint(p['Endpoint'])
        if 'PersistentKeepalive' in p:
            p['PersistentKeepalive'] = number(p['PersistentKeepalive'], 0, 65535)
        routes = [ipaddress.ip_network(x.strip(), strict=False) for x in p['AllowedIPs'].split(',')]
        if len(routes) > 128 or any(x.is_loopback or x.is_link_local or x.is_multicast for x in routes):
            raise ValueError("Invalid or excessive AllowedIPs routes")
        all_routes.extend(routes)
        p['AllowedIPs'] = ', '.join(str(x) for x in routes)
    if len(all_routes) > 128:
        raise ValueError('Maximum 128 total AllowedIPs routes')
    for addr in dns:
        if not any(ipaddress.ip_address(addr) in route for route in all_routes):
            raise ValueError("DNS server is not covered by AllowedIPs")
    return Config(interface, peers, addresses, dns, searches, mtu)
