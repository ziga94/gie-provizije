#!/usr/bin/env python3
"""
GIE Provizije - Lokalni streznik
Pozene z: python zeni_streznik.py
"""
import http.server
import json
import urllib.request
import urllib.error
import urllib.parse
import os

PORT = int(os.environ.get("PORT", 8765))
API_KEY_FILE = "gie_api_key.txt"
DATABASE_URL = os.environ.get("DATABASE_URL", "")

def get_db():
    """Get PostgreSQL connection."""
    if DATABASE_URL:
        try:
            import psycopg2
            return psycopg2.connect(DATABASE_URL, sslmode='require')
        except Exception as e:
            print("  DB napaka:", e)
    return None

def init_db():
    """Create tables if not exist."""
    conn = get_db()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS gie_data (
                    id INTEGER PRIMARY KEY DEFAULT 1,
                    entries TEXT NOT NULL DEFAULT '[]',
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)
            cur.execute("INSERT INTO gie_data (id, entries) VALUES (1, '[]') ON CONFLICT (id) DO NOTHING")
            conn.commit()
            cur.close()
            conn.close()
            print("  PostgreSQL: tabela inicializirana")
        except Exception as e:
            print("  DB init napaka:", e)

def load_data():
    """Load data from PostgreSQL or fallback to file."""
    conn = get_db()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT entries FROM gie_data WHERE id = 1")
            row = cur.fetchone()
            cur.close()
            conn.close()
            if row:
                return row[0]
        except Exception as e:
            print("  DB load napaka:", e)
    # Fallback to file
    if os.path.exists("gie_data.json"):
        try:
            with open("gie_data.json", 'r', encoding='utf-8') as f:
                return f.read()
        except:
            pass
    return '[]'

def save_data(data):
    """Save data to PostgreSQL or fallback to file."""
    conn = get_db()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("UPDATE gie_data SET entries = %s, updated_at = NOW() WHERE id = 1", (data,))
            if cur.rowcount == 0:
                cur.execute("INSERT INTO gie_data (id, entries) VALUES (1, %s)", (data,))
            conn.commit()
            cur.close()
            conn.close()
            return True
        except Exception as e:
            print("  DB save napaka:", e)
    # Fallback to file
    try:
        with open("gie_data.json", 'w', encoding='utf-8') as f:
            f.write(data)
        return True
    except Exception as e:
        print("  File save napaka:", e)
        return False

def get_api_key():
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return key
    if os.path.exists(API_KEY_FILE):
        with open(API_KEY_FILE, 'r') as f:
            return f.read().strip()
    return None

def save_api_key(key):
    with open(API_KEY_FILE, 'w') as f:
        f.write(key)

PROMPT = (
    "Preberi ta racun in vrni SAMO JSON objekt brez kakrsnega koli besedila."
    " Poisce: datum racuna (date YYYY-MM-DD), datum zapadlosti (due YYYY-MM-DD pri Due date, Scadenze ali Bank transfer),"
    " stevilko racuna (invoice), valuto (currency: EUR/USD/GBP itd),"
    " skupni znesek v originalni valuti (amount_orig = Total to pay)."
    " KLJUCNO - NAKUP ali PRODAJA:"
    " Ce je kupec Continental Semences ali Continental Semences Spa -> je_nakup=true, client=ime prodajalca."
    " Ce je Continental prodajalec -> je_nakup=false, client=ime kupca."
    " POSTAVKE - za vsako vrstico v tabeli:"
    " desc = kratek opis semena (samo ime vrste, npr MEDICAGO SATIVA, TRIFOLIUM PRATENSE, TURF GRASS MIXTURE),"
    " net = Net Amount v originalni valuti,"
    " qty = kolicina v KG (stevilo pred besedo KG ali Kg). Ce kolicine ni qty=0."
    " Freight/Transport postavke: desc=Freight, net=znesek, qty=0."
    " amount_orig = skupni znesek."
    ' Vrni IZKLJUCNO ta JSON: {"amount":0,"amount_orig":0,"currency":"EUR","date":null,"due":null,"invoice":null,"client":null,"je_nakup":false,"items":[{"desc":"ime semena","net":0,"qty":0}]}'
)

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print("  >> " + format % args)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def respond(self, code, data):
        result = json.dumps(data).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(result))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(result)

    def do_GET(self):
        if self.path == '/':
            html_file = 'provizije_skupina.html'
            if os.path.exists(html_file):
                with open(html_file, 'rb') as f:
                    content = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', len(content))
                self.end_headers()
                self.wfile.write(content)
            else:
                self.send_error(404, 'provizije_skupina.html not found')

        elif self.path == '/data':
            data = load_data()
            result = data.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', len(result))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(result)

        elif self.path == '/ping':
            self.respond(200, {'ok': True})

        elif self.path.startswith('/racuni/'):
            filename = urllib.parse.unquote(self.path[8:])
            filename = os.path.basename(filename)
            racuni_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'racuni')
            filepath = os.path.join(racuni_dir, filename)
            import re
            if not os.path.exists(filepath):
                base_name = re.sub(r'_racun_[0-9]+\.pdf$', '_racun.pdf', filepath)
                if os.path.exists(base_name):
                    filepath = base_name
            if os.path.exists(filepath):
                with open(filepath, 'rb') as fp:
                    content = fp.read()
                self.send_response(200)
                self.send_header('Content-Type', 'application/pdf')
                self.send_header('Content-Length', len(content))
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(content)
            else:
                self.send_error(404)

        elif self.path.startswith('/rate/'):
            currency = self.path[6:].upper()
            try:
                url = 'https://open.er-api.com/v6/latest/{}'.format(currency)
                req = urllib.request.urlopen(url, timeout=5)
                data = json.loads(req.read())
                rate = data['rates']['EUR']  # open.er-api.com
                self.respond(200, {'rate': rate, 'currency': currency})
                print("  Tecaj {}/EUR: {}".format(currency, rate))
            except Exception as ex:
                self.respond(500, {'error': str(ex)})

        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == '/save':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            try:
                req = json.loads(body)
                data = req.get('data', '[]')
                if save_data(data):
                    result = json.dumps({'ok': True}).encode('utf-8')
                    try:
                        count = len(json.loads(data))
                        print("  Shranjeno: {} vnosov".format(count))
                    except:
                        pass
                else:
                    result = json.dumps({'ok': False}).encode('utf-8')
            except Exception as e:
                result = json.dumps({'ok': False, 'error': str(e)}).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', len(result))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(result)

        elif self.path == '/pdf-info':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            req = json.loads(body)
            try:
                import base64
                import io
                import pypdf
                pdf_data = base64.b64decode(req['file'])
                reader = pypdf.PdfReader(io.BytesIO(pdf_data))
                num_pages = len(reader.pages)
                invoice_pages = list(range(num_pages))

                if num_pages > 4:
                    try:
                        writer2 = pypdf.PdfWriter()
                        for p in range(4):
                            writer2.add_page(reader.pages[p])
                        out2 = io.BytesIO()
                        writer2.write(out2)
                        ai_b64 = base64.b64encode(out2.getvalue()).decode('utf-8')
                        print("  Skrcano na 4 strani za pdf-info AI")
                    except:
                        ai_b64 = req['file']
                else:
                    ai_b64 = req['file']

                _ak = get_api_key()
                if num_pages > 1 and _ak:
                    print("  Preverjam katere strani so racun ({} strani)...".format(num_pages))
                    payload = json.dumps({
                        "model": "claude-sonnet-4-6",
                        "max_tokens": 200,
                        "system": "You are a document analyzer. Respond with ONLY a JSON object.",
                        "messages": [{
                            "role": "user",
                            "content": [
                                {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": ai_b64}},
                                {"type": "text", "text": ("This PDF has " + str(num_pages) + " pages. Which pages are INVOICE/FATTURA? Other pages may be CMR, delivery notes. Return ONLY JSON: {\"invoice_pages\": [0, 1]} (0-indexed page numbers)")}
                            ]
                        }]
                    }).encode("utf-8")
                    ai_req = urllib.request.Request(
                        "https://api.anthropic.com/v1/messages",
                        data=payload,
                        headers={"Content-Type": "application/json", "x-api-key": _ak, "anthropic-version": "2023-06-01"}
                    )
                    ai_resp = urllib.request.urlopen(ai_req, timeout=30)
                    ai_data = json.loads(ai_resp.read())
                    ai_text = "".join(b.get("text","") for b in ai_data.get("content",[]))
                    start = ai_text.find("{"); end = ai_text.rfind("}")
                    if start >= 0 and end > start:
                        ai_json = json.loads(ai_text[start:end+1])
                        invoice_pages = ai_json.get("invoice_pages", list(range(num_pages)))
                    print("  Strani racuna: {}".format(invoice_pages))

                # Save original PDF to racuni folder
                racuni_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'racuni')
                os.makedirs(racuni_dir, exist_ok=True)
                filename = req.get('filename', 'racun.pdf')
                filename = ''.join(c for c in filename if c.isalnum() or c in '._- ')
                filepath = os.path.join(racuni_dir, filename)
                base, ext = os.path.splitext(filepath)
                counter = 1
                while os.path.exists(filepath):
                    filepath = base + '_' + str(counter) + ext
                    counter += 1
                with open(filepath, 'wb') as f:
                    f.write(pdf_data)
                print("  Shranjen PDF: {}".format(filepath))

                result = json.dumps({"pages": num_pages, "invoice_pages": invoice_pages}).encode("utf-8")
            except Exception as e:
                print("  Napaka pdf-info:", e)
                result = json.dumps({"pages": 1, "invoice_pages": [0], "error": str(e)}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", len(result))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(result)

        elif self.path == '/extract-pages':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            req = json.loads(body)
            try:
                import base64
                import io
                import pypdf
                pdf_data = base64.b64decode(req['file'])
                pages = req['pages']
                reader = pypdf.PdfReader(io.BytesIO(pdf_data))
                writer = pypdf.PdfWriter()
                for p in pages:
                    if 0 <= p < len(reader.pages):
                        writer.add_page(reader.pages[p])
                out = io.BytesIO()
                writer.write(out)
                racuni_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'racuni')
                os.makedirs(racuni_dir, exist_ok=True)
                orig_name = req.get('filename', 'racun.pdf')
                orig_name = ''.join(ch for ch in orig_name if ch.isalnum() or ch in '._- ')
                base, ext = os.path.splitext(orig_name)
                extracted_name = base + '_racun' + ext
                extracted_path = os.path.join(racuni_dir, extracted_name)
                counter = 1
                while os.path.exists(extracted_path):
                    extracted_path = os.path.join(racuni_dir, base + '_racun_' + str(counter) + ext)
                    counter += 1
                with open(extracted_path, 'wb') as f_out:
                    f_out.write(out.getvalue())
                out_b64 = base64.b64encode(out.getvalue()).decode('utf-8')
                result = json.dumps({'file': out_b64, 'saved_name': os.path.basename(extracted_path)}).encode('utf-8')
                print("  Izvlecene strani: {} od {}, shranjeno: {}".format(len(pages), len(reader.pages), extracted_path))
            except Exception as e:
                result = json.dumps({'error': str(e)}).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', len(result))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(result)

        elif self.path == '/scan':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            req = json.loads(body)
            api_key = get_api_key()
            if not api_key:
                self.respond(400, {'error': 'API key not set'})
                return
            try:
                file_b64 = req['file']
                media_type = req.get('media_type', 'application/pdf')
                if media_type == 'application/pdf':
                    file_content = {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": file_b64}}
                else:
                    file_content = {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": file_b64}}

                if media_type == 'application/pdf':
                    try:
                        import base64 as _b64
                        import io
                        import pypdf
                        pdf_data = _b64.b64decode(file_b64)
                        reader = pypdf.PdfReader(io.BytesIO(pdf_data))
                        if len(reader.pages) > 2:
                            writer = pypdf.PdfWriter()
                            for p in range(min(2, len(reader.pages))):
                                writer.add_page(reader.pages[p])
                            out = io.BytesIO()
                            writer.write(out)
                            file_b64 = _b64.b64encode(out.getvalue()).decode('utf-8')
                            file_content = {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": file_b64}}
                            print("  Skrcano na 2 strani za AI skeniranje")
                    except Exception as ex:
                        print("  Napaka skrcanja:", ex)

                print("  Posiljam racun AI ({}), cakam...".format(media_type))
                payload = json.dumps({
                    "model": "claude-sonnet-4-6",
                    "max_tokens": 1000,
                    "system": "You are a JSON extractor. You MUST respond with ONLY a valid JSON object. No text, no explanation, no markdown. Just the JSON object.",
                    "messages": [{"role": "user", "content": [file_content, {"type": "text", "text": PROMPT}]}]
                }).encode('utf-8')

                ai_req = urllib.request.Request(
                    "https://api.anthropic.com/v1/messages",
                    data=payload,
                    headers={"Content-Type": "application/json", "x-api-key": api_key, "anthropic-version": "2023-06-01"}
                )
                resp = urllib.request.urlopen(ai_req, timeout=60)
                resp_data = json.loads(resp.read())
                content_blocks = resp_data.get('content', [])
                print("  Content blocks:", len(content_blocks), [b.get('type') for b in content_blocks])
                raw = "".join(b.get("text", "") for b in content_blocks if b.get("type") == "text")
                print("  Raw response: '{}'".format(raw[:200]))

                start = raw.find('{'); end = raw.rfind('}')
                if start < 0 or end < 0:
                    self.respond(400, {'error': 'No JSON in response'})
                    return
                data = json.loads(raw[start:end+1])

                # Categorize items
                forage_amount = 0
                mixture_amount = 0
                total_qty = 0
                if data.get('items') and not data.get('je_nakup'):
                    for item in data['items']:
                        desc = (item.get('desc') or '').upper()
                        net = float(item.get('net') or 0)
                        qty = float(item.get('qty') or 0)
                        total_qty += qty
                        if any(w in desc for w in ['MIX', 'MIXTURE', 'BLEND']):
                            mixture_amount += net
                        elif desc not in ['FREIGHT', 'TRANSPORT', 'PACKING']:
                            forage_amount += net

                data['forage_amount'] = round(forage_amount, 2)
                data['mixture_amount'] = round(mixture_amount, 2)
                data['total_qty'] = round(total_qty, 2)

                # Currency conversion
                currency = data.get('currency', 'EUR').upper()
                if currency != 'EUR':
                    try:
                        url = 'https://open.er-api.com/v6/latest/{}'.format(currency)
                        rate_req = urllib.request.urlopen(url, timeout=5)
                        rate_data = json.loads(rate_req.read())
                        rate = rate_data['rates']['EUR']
                        orig = data.get('amount', 0) or 0
                        data['amount'] = round(orig * rate, 2)
                        data['exchange_rate'] = rate
                        data['amount_orig'] = orig
                        if data.get('items'):
                            for item in data['items']:
                                item['net'] = round((item.get('net') or 0) * rate, 2)
                        data['forage_amount'] = round(forage_amount * rate, 2)
                        data['mixture_amount'] = round(mixture_amount * rate, 2)
                        print("  Pretvorba {} -> EUR: tecaj={}".format(currency, rate))
                    except Exception as ex:
                        print("  Napaka pretvorbe valute:", ex)

                print("  Zaznano: znesek={} {}, datum={}, zapadlost={}, racun={}, stranka={}, forage={}, mixture={}".format(
                    data.get('amount_orig', data.get('amount')), currency, data.get('date'), data.get('due'),
                    data.get('invoice'), data.get('client'), data.get('forage_amount'), data.get('mixture_amount')))

                self.respond(200, data)

            except urllib.error.HTTPError as e:
                err = e.read().decode()
                print("  API napaka:", err[:200])
                if 'invalid_api_key' in err or 'authentication' in err.lower():
                    self.respond(401, {'error': 'Invalid API key'})
                else:
                    self.respond(500, {'error': err[:200]})
            except Exception as e:
                print("  Napaka:", str(e))
                self.respond(500, {'error': str(e)})

        elif self.path == '/setkey':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            req = json.loads(body)
            key = req.get('key', '')
            if key.startswith('sk-ant'):
                save_api_key(key)
                self.respond(200, {'ok': True})
            else:
                self.respond(400, {'ok': False})

        else:
            self.respond(404, {'error': 'Not found'})


if __name__ == '__main__':
    init_db()
    api = get_api_key()
    print("=" * 50)
    print("  GIE Provizije - Lokalni streznik")
    print("=" * 50)
    print("  API kljuc:", "nastavljen (" + api[:15] + "...)" if api else "NI NASTAVLJEN - nastavite ga v aplikaciji")
    print("  Odpri brskalnik: http://localhost:" + str(PORT))
    print("  Za zaustavitev pritisni Ctrl+C")
    print("  PostgreSQL:", "povezan" if DATABASE_URL else "ni - uporaba lokalnih datotek")
    print("=" * 50)

    server = http.server.HTTPServer(('0.0.0.0', PORT), Handler)
    server.serve_forever()
