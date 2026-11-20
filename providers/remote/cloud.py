"""Official RunPod REST/GraphQL and Vast HTTP APIs; no SDK or credential persistence.

Provider response bodies/errors are deliberately never returned. Redirects are refused.
Only loopback endpoints may override production URLs (offline tests).
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request

from .config import RemoteError, api_key, positive


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Cloud:
    def __init__(self, kind):
        self.kind = kind
        self.base = {'runpod': 'https://rest.runpod.io/v1',
                     'vast': 'https://console.vast.ai/api/v0'}[kind]
        override = os.environ.get('CHAR3D_REMOTE_' + kind.upper() + '_BASE')
        if override:
            u = urllib.parse.urlsplit(override)
            if u.scheme != 'http' or u.hostname not in ('127.0.0.1', 'localhost', '::1') or u.username:
                raise RemoteError('Provider test URL must be HTTP loopback')
            self.base = override.rstrip('/')
        self.graphql = (self.base + '/graphql' if override else 'https://api.runpod.io/graphql')

    def request(self, method, path='', body=None, graphql=False, v1=False):
        key = api_key(self.kind)
        url = self.graphql if graphql else self.base + path
        if v1 and self.base.endswith('/api/v0'):
            url = self.base.removesuffix('/v0')+'/v1'+path
        req = urllib.request.Request(url, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
        try:
            with urllib.request.build_opener(NoRedirect).open(req, timeout=15) as resp:
                raw = resp.read(4 * 1024 * 1024)
            data = json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            if exc.code == 404 and method == 'DELETE':
                return {}
            raise RemoteError(f'{self.kind} HTTP {exc.code}; provider details redacted') from None
        except Exception:
            raise RemoteError(f'{self.kind} request failed; provider details redacted') from None
        if key in json.dumps(data, ensure_ascii=False):
            raise RemoteError(f'{self.kind} returned credential material; details redacted')
        if isinstance(data, dict) and (data.get('errors') or data.get('success') is False):
            raise RemoteError(f'{self.kind} rejected request; provider details redacted')
        return data

    def quote(self, t):
        if self.kind == 'runpod':
            data = self.request('POST', body={'query': '{ gpuTypes { id displayName securePrice communityPrice } }'}, graphql=True)
            choices = data['data']['gpuTypes']
            field = 'communityPrice' if t.get('cloud_type') == 'COMMUNITY' else 'securePrice'
            matches = [g for g in choices if g['id'] == t['gpu_type']]
            if not matches or matches[0].get(field) is None:
                raise RemoteError('Requested RunPod GPU has no current on-demand price')
            offer = {'offer_id': t['gpu_type'], 'gpu_type': t['gpu_type'],
                     'hourly_price_usd': positive(matches[0][field], 'provider hourly price')}
        else:
            data = self.request('POST', '/bundles/', {
                'limit': 100, 'type': 'on-demand', 'verified': {'eq': True},
                'rentable': {'eq': True}, 'rented': {'eq': False}, 'num_gpus': {'eq': 1},
                'gpu_name': {'eq': t['gpu_type']}, 'disk_space': {'gte': t['disk_gb']},
                'inet_up_cost': {'eq': 0}, 'inet_down_cost': {'eq': 0},
                'dph_total': {'lte': t['max_hourly_usd']}, 'order': [['dph_total', 'asc']]})
            offers = data.get('offers', [])
            if isinstance(offers, dict):
                offers = [offers]
            offers = [o for o in offers if o.get('gpu_name') == t['gpu_type'] and
                      o.get('num_gpus', 1) == 1 and not o.get('inet_up_cost') and not o.get('inet_down_cost')]
            if not offers:
                raise RemoteError('No matching Vast offer with free data transfer under the price cap')
            o = min(offers, key=lambda v: positive(v['dph_total'], 'provider hourly price'))
            # storage_cost is USD/GB/month; allocate exactly disk_gb.
            price = positive(o['dph_total'], 'provider hourly price') + positive(
                o.get('storage_cost', 0), 'provider storage price', zero=True)*t['disk_gb']/720
            offer = {'offer_id': str(o['id']), 'gpu_type': o['gpu_name'], 'hourly_price_usd': price}
        if offer['hourly_price_usd'] > t['max_hourly_usd']:
            raise RemoteError('Provider price exceeds max_hourly_usd')
        return offer

    def instances(self):
        data = self.request('GET', '/pods' if self.kind == 'runpod' else '/instances/', v1=self.kind == 'vast')
        return data if isinstance(data, list) else data.get('instances', [])

    def find(self, label):
        return [x for x in self.instances() if (x.get('name') or x.get('label')) == label]

    def create(self, t, offer, label):
        public = Path(t['public_key']).expanduser().read_text().strip()
        if not public.startswith(('ssh-ed25519 ', 'ssh-rsa ', 'ecdsa-sha2-')) or '\n' in public:
            raise RemoteError('public_key must point to a single SSH public key')
        if self.kind == 'runpod':
            data = self.request('POST', '/pods', {
                'name': label, 'imageName': t['image'], 'computeType': 'GPU', 'gpuCount': 1,
                'gpuTypeIds': [offer['offer_id']], 'cloudType': t.get('cloud_type', 'SECURE'),
                'interruptible': False, 'containerDiskInGb': t['disk_gb'], 'volumeInGb': 0,
                'ports': ['22/tcp'], 'supportPublicIp': True, 'env': {'PUBLIC_KEY': public}})
            return str(data['id'])
        data = self.request('PUT', '/asks/' + offer['offer_id'] + '/', {
            'client_id': 'me', 'image': t['image'], 'disk': t['disk_gb'],
            'runtype': 'ssh', 'label': label,
            'price': offer['hourly_price_usd']})
        return str(data['new_contract'])

    def attach_key(self, t, ident):
        if self.kind == 'vast':
            public = Path(t['public_key']).expanduser().read_text().strip()
            self.request('POST', '/instances/'+urllib.parse.quote(str(ident), safe='')+'/ssh/', {'ssh_key': public})

    def inspect(self, ident):
        if self.kind == 'runpod':
            data = self.request('GET', '/pods/' + urllib.parse.quote(str(ident), safe=''))
        else:
            data = self.request('GET', '/instances/' + urllib.parse.quote(str(ident), safe='') + '/')
            data = data.get('instances', data)
            if isinstance(data, list):
                data = data[0]
        return data

    def connection(self, t, data, approved_rate):
        price = data.get('costPerHr') if self.kind == 'runpod' else data.get('dph_total')
        if price is None:
            return None
        if positive(price, 'actual hourly price') > approved_rate + 1e-8:
            raise RemoteError('Allocated instance price exceeds the confirmed quote')
        if self.kind == 'runpod':
            host, port = data.get('publicIp'), (data.get('portMappings') or {}).get('22')
        else:
            host, port = data.get('ssh_host'), data.get('ssh_port')
        if not host or not port:
            return None
        if not isinstance(host, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.:-]*', host):
            raise RemoteError('Provider returned an invalid SSH host')
        if not 1 <= int(port) <= 65535:
            raise RemoteError('Provider returned an invalid SSH port')
        return dict(t, host=host, port=int(port), user=t.get('user', 'root'))

    def terminate(self, ident):
        ident = urllib.parse.quote(str(ident), safe='')
        return self.request('DELETE', '/pods/' + ident if self.kind == 'runpod' else '/instances/' + ident + '/')

    @staticmethod
    def billing(data):
        # Only report provider totals when actually supplied; never label our clock as an invoice.
        return {k: data[k] for k in ('total_cost', 'billed_seconds', 'totalCost', 'billedSeconds') if k in data}

    def final_billing(self, ident, started):
        if self.kind != 'runpod':
            return {}
        query = urllib.parse.urlencode(dict(podId=ident, grouping='podId', bucketSize='hour',
            startTime=datetime.fromtimestamp(started, timezone.utc).isoformat()))
        records = self.request('GET', '/billing/pods?'+query)
        if not isinstance(records, list):
            return {}
        records = [r for r in records if str(r.get('podId')) == str(ident)]
        if not records:
            return {}
        bill = {'billed_cost_usd': sum(positive(r['amount'], 'billed amount', zero=True) for r in records),
                'source': 'provider billing history', 'provisional': True}
        if all('timeBilledMs' in r for r in records):
            bill['billed_seconds'] = sum(positive(r['timeBilledMs'], 'billed time', zero=True) for r in records)/1000
        return bill
