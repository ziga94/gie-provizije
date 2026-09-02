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
import urllib.request
import urllib.error

PORT = 8765
API_KEY_FILE = "gie_api_key.txt"

def get_api_key():
    if os.path.exists(API_KEY_FILE):
        with open(API_KEY_FILE, 'r') as f:
            return f.read().strip()
    return None

def save_api_key(key):
    with open(API_KEY_FILE, 'w') as f:
        f.write(key.strip())

PROMPT = (
    "Preberi ta racun in vrni SAMO JSON objekt brez kakrsnega koli besedila."
    " Poisce: datum racuna (date YYYY-MM-DD), datum zapadlosti (due YYYY-MM-DD pri Due date, Scadenze ali Bank transfer),"
    " stevilko racuna (invoice), valuto (currency: EUR/USD/GBP itd),"
    " skupni znesek v originalni valuti (amount = Total to pay ali Total Amount)."
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
        print("  >>", args[0] if args else format)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

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

        elif self.path.startswith('/rate/'):
            # Get exchange rate via server
            currency = self.path[6:].upper()
            try:
                url = 'https://api.frankfurter.app/latest?from={}&to=EUR'.format(currency)
                req = urllib.request.urlopen(url, timeout=5)
                data = json.loads(req.read())
                rate = data['rates']['EUR']
                result = json.dumps({'rate': rate, 'currency': currency}).encode('utf-8')
                print("  Tecaj {}/EUR: {}".format(currency, rate))
            except Exception as ex:
                result = json.dumps({'error': str(ex)}).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Content-Length', len(result))
            self.end_headers()
            self.wfile.write(result)

        elif self.path == '/ping':
            self.respond(200, {'ok': True})
        elif self.path.startswith('/racuni/'):
            filename = urllib.parse.unquote(self.path[8:])
            filename = os.path.basename(filename)
            racuni_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'racuni')
            filepath = os.path.join(racuni_dir, filename)
            print('  Serviram:', filepath)
            # Try exact filename, then without suffix number
            if not os.path.exists(filepath):
                import re
                base_name = re.sub(r'_racun_\d+\.pdf$', '_racun.pdf', filepath)
                if os.path.exists(base_name):
                    filepath = base_name
                else:
                    base_name2 = re.sub(r'_\d+\.pdf$', '.pdf', filepath)
                    if os.path.exists(base_name2):
                        filepath = base_name2
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
                print('  404 - ni najdeno:', filepath)
                self.send_error(404)
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == '/scan':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(length))
                file_b64 = body.get('file')
                media_type = body.get('media_type', 'application/pdf')
                api_key = get_api_key()

                if not api_key:
                    self.respond(400, {'error': 'NO_API_KEY'})
                    return

                print("  Posiljam racun AI ({}), cakam...".format(media_type))

                if 'pdf' in media_type:
                    file_content = {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": file_b64
                        }
                    }
                else:
                    file_content = {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": file_b64
                        }
                    }

                # If PDF has many pages, trim to first 2 pages to reduce tokens
                if media_type == 'application/pdf':
                    try:
                        import io, pypdf, base64
                        pdf_data = base64.b64decode(file_b64)
                        reader = pypdf.PdfReader(io.BytesIO(pdf_data))
                        if len(reader.pages) > 2:
                            writer = pypdf.PdfWriter()
                            for p in range(min(2, len(reader.pages))):
                                writer.add_page(reader.pages[p])
                            out = io.BytesIO()
                            writer.write(out)
                            file_b64 = base64.b64encode(out.getvalue()).decode('utf-8')
                            file_content = {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": file_b64}}
                            print("  Skrcano na 2 strani za AI skeniranje")
                    except Exception as ex:
                        print("  Napaka skrcanja:", ex)

                payload = json.dumps({
                    "model": "claude-sonnet-4-6",
                    "max_tokens": 1000,
                    "system": "You are a JSON extractor. You MUST respond with ONLY a valid JSON object. No text, no explanation, no markdown. Just the JSON object.",
                    "messages": [{
                        "role": "user",
                        "content": [
                            file_content,
                            {"type": "text", "text": PROMPT}
                        ]
                    }]
                }).encode('utf-8')

                req = urllib.request.Request(
                    'https://api.anthropic.com/v1/messages',
                    data=payload,
                    headers={
                        'Content-Type': 'application/json',
                        'x-api-key': api_key,
                        'anthropic-version': '2023-06-01'
                    }
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    result = json.loads(resp.read())
                    content_blocks = result.get('content',[])
                    print("  Content blocks:", len(content_blocks), [b.get('type') for b in content_blocks])
                    text = ''.join(b.get('text','') for b in content_blocks)
                    text = text.strip()
                    print("  Raw response:", repr(text[:300]))
                    # Try to extract JSON object from anywhere in the response
                    import re as _re
                    # Remove markdown code blocks
                    text = _re.sub(r'```json\s*', '', text)
                    text = _re.sub(r'```\s*', '', text)
                    # Find JSON object (handle nested braces)
                    start = text.find('{')
                    if start >= 0:
                        depth = 0
                        end = start
                        for idx2, ch in enumerate(text[start:]):
                            if ch == '{': depth += 1
                            elif ch == '}': 
                                depth -= 1
                                if depth == 0:
                                    end = start + idx2
                                    break
                        text = text[start:end+1]
                    text = text.strip()
                    if not text: raise ValueError("No JSON found in response")
                    data = json.loads(text)
                    # Check if nakup
                    if data.get('je_nakup'):
                        data['forage_amount'] = 0
                        data['mixture_amount'] = 0
                        data['nakup_amount'] = float(data.get('amount') or 0)
                        print("  NAKUP zaznан: znesek={}, datum={}, racun={}, stranka={}".format(
                            data.get('amount'), data.get('date'), data.get('invoice'), data.get('client')))
                    else:
                        # Categorize items by MIX/MIXTURE/BLEND keyword
                        if 'items' in data and data['items']:
                            forage = 0
                            mixture = 0
                            mix_keywords = ['mix', 'mixture', 'blend']
                            for item in data['items']:
                                desc = (item.get('desc') or '').lower()
                                net = float(item.get('net') or 0)
                                is_mix = any(kw in desc for kw in mix_keywords)
                                if is_mix:
                                    mixture += net
                                else:
                                    forage += net
                            data['forage_amount'] = round(forage, 2)
                            data['mixture_amount'] = round(mixture, 2)
                        print("  Zaznano: znesek={}, datum={}, zapadlost={}, racun={}, stranka={}, forage={}, mixture={}".format(
                            data.get('amount'), data.get('date'), data.get('due'),
                            data.get('invoice'), data.get('client'), data.get('forage_amount'), data.get('mixture_amount')))
                    self.respond(200, data)

            except urllib.error.HTTPError as e:
                err = e.read().decode()
                print("  API napaka:", err[:200])
                if 'invalid_api_key' in err or 'authentication' in err.lower():
                    self.respond(401, {'error': 'INVALID_API_KEY'})
                else:
                    self.respond(500, {'error': str(e)})
            except Exception as e:
                print("  Napaka:", str(e))
                self.respond(500, {'error': str(e)})



        elif self.path.startswith('/racuni/'):
            filename = urllib.parse.unquote(self.path[8:])
            filename = os.path.basename(filename)
            racuni_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'racuni')
            filepath = os.path.join(racuni_dir, filename)
            print('  Serviram:', filepath)
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
                self.send_response(404)
                self.end_headers()
            return

        elif self.path == '/pdf-info':
            # Returns number of pages and AI detection of invoice pages
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
                invoice_pages = list(range(num_pages))  # default all pages
                # Get api_key
                _ak = ''
                try:
                    with open('gie_api_key.txt','r') as _f: _ak = _f.read().strip()
                except: pass

                # Save original PDF to racuni folder
                import os
                racuni_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'racuni')
                os.makedirs(racuni_dir, exist_ok=True)
                filename = req.get('filename', 'racun.pdf')
                # Sanitize filename
                filename = ''.join(c for c in filename if c.isalnum() or c in '._- ')
                filepath = os.path.join(racuni_dir, filename)
                # If file exists add number
                base, ext = os.path.splitext(filepath)
                counter = 1
                while os.path.exists(filepath):
                    filepath = base + '_' + str(counter) + ext
                    counter += 1
                with open(filepath, 'wb') as f:
                    f.write(pdf_data)
                print("  Shranjen PDF: {}".format(filepath))

                # Trim to max 4 pages for AI detection to save tokens
                if num_pages > 4:
                    try:
                        import io, pypdf, base64 as _b64
                        reader2 = pypdf.PdfReader(io.BytesIO(pdf_data))
                        writer2 = pypdf.PdfWriter()
                        for p in range(4):
                            writer2.add_page(reader2.pages[p])
                        out2 = io.BytesIO()
                        writer2.write(out2)
                        ai_b64 = _b64.b64encode(out2.getvalue()).decode('utf-8')
                        print("  Skrcano na 4 strani za pdf-info AI")
                    except:
                        ai_b64 = req['file']
                else:
                    ai_b64 = req['file']

                if num_pages > 1 and _ak:
                    # Use AI to detect which pages are invoice
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
            # Extracts selected pages from PDF
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            req = json.loads(body)
            try:
                import base64
                import io
                import pypdf
                pdf_data = base64.b64decode(req['file'])
                pages = req['pages']  # list of page numbers (0-indexed)
                reader = pypdf.PdfReader(io.BytesIO(pdf_data))
                writer = pypdf.PdfWriter()
                for p in pages:
                    if 0 <= p < len(reader.pages):
                        writer.add_page(reader.pages[p])
                out = io.BytesIO()
                writer.write(out)
                # Save extracted PDF to disk
                import os
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
                result = json.dumps({'file': out_b64, 'saved_path': extracted_path, 'saved_name': os.path.basename(extracted_path)}).encode('utf-8')
                print("  Izvlecene strani: {} od {}, shranjeno: {}".format(len(pages), len(reader.pages), extracted_path))
            except Exception as e:
                result = json.dumps({'error': str(e)}).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', len(result))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(result)

        elif self.path == '/setkey':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(length))
                key = body.get('key', '').strip()
                if key:
                    save_api_key(key)
                    print("  API kljuc shranjen.")
                    self.respond(200, {'ok': True})
                else:
                    self.respond(400, {'error': 'Empty key'})
            except Exception as e:
                self.respond(500, {'error': str(e)})
        else:
            self.send_error(404)

    def respond(self, code, data):
        body = json.dumps(data).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

if __name__ == '__main__':
    print("")
    print("=" * 50)
    print("  GIE Provizije - Lokalni streznik")
    print("=" * 50)
    print("")
    api = get_api_key()
    if api:
        print("  API kljuc: nastavljen (" + api[:12] + "...)")
    else:
        print("  API kljuc: NI NASTAVLJEN - nastavite ga v aplikaciji")
    print("")
    print("  Odpri brskalnik: http://localhost:" + str(PORT))
    print("")
    print("  Za zaustavitev pritisni Ctrl+C")
    print("=" * 50)
    print("")

    server = http.server.HTTPServer(('localhost', PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStreznik zaustavljen.")
