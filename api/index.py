from flask import Flask, request
import requests, json, os, re, datetime, math, ast, operator, difflib, base64
from bs4 import BeautifulSoup
import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__)

db = None
try:
    key_b64 = os.environ.get('FIREBASE_KEY')
    if key_b64:
        key_json = json.loads(base64.b64decode(key_b64))
        cred = credentials.Certificate(key_json)
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred)
        db = firestore.client()
except Exception as e:
    print("Firebase erro:", e)

def get_cerebro():
    if db:
        try:
            doc = db.collection('sistema').document('cerebro').get()
            if doc.exists:
                return doc.to_dict()
        except: pass
    return {"conhecimento": {}, "buscas": 0, "total": 0}

def salvar_cerebro(cerebro):
    if db:
        try: db.collection('sistema').document('cerebro').set(cerebro)
        except: pass

ultima = {"pergunta": "", "resposta": ""}

OPERADORES_SEGUROS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos}
def avaliar_no(node):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)): return node.value
    elif isinstance(node, ast.BinOp):
        return OPERADORES_SEGUROS[type(node.op)](avaliar_no(node.left), avaliar_no(node.right))
    elif isinstance(node, ast.UnaryOp):
        return OPERADORES_SEGUROS[type(node.op)](avaliar_no(node.operand))
    raise TypeError("err")

def responder(pergunta):
    global ultima
    cerebro = get_cerebro()
    p = pergunta.lower().strip()
    cerebro["total"] = cerebro.get("total",0)+1
    if any(x in p for x in ['qual seu nome','quem é você','quem e voce','seu nome']):
        return "Meu nome é Alpha! Sou criada pelo Elias Tchalo, v6.0 mundial Vercel+Firebase! ✨"
    chaves = list(cerebro.get("conhecimento", {}).keys())
    if chaves:
        match = difflib.get_close_matches(p.replace("?", ""), chaves, n=1, cutoff=0.75)
        if match:
            resposta_salva = cerebro["conhecimento"][match[0]]
            ultima = {"pergunta": pergunta, "resposta": resposta_salva}
            salvar_cerebro(cerebro)
            return f"{resposta_salva}\n\n🧠 [Firebase]"
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        pergunta_limpa = re.sub(r'(o que é|quem é|qual é|\?)', '', p).strip()
        url_search = f"https://pt.wikipedia.org/w/api.php?action=query&list=search&srsearch={pergunta_limpa}&format=json"
        r = requests.get(url_search, timeout=4, headers=headers)
        if r.status_code == 200:
            results = r.json().get("query", {}).get("search", [])
            if results:
                titulo = results[0]["title"].replace(" ", "_")
                url_sum = f"https://pt.wikipedia.org/api/rest_v1/page/summary/{titulo}"
                r2 = requests.get(url_sum, timeout=4, headers=headers)
                if r2.status_code == 200:
                    d = r2.json()
                    if d.get("extract"):
                        resposta = f"📚 {d['extract'][:700]}..."
                        cerebro["conhecimento"][p.replace('?','').strip()] = resposta
                        salvar_cerebro(cerebro)
                        return resposta
    except: pass
    salvar_cerebro(cerebro)
    return f"❌ Não encontrei '{pergunta}'. Ensine: ensina: {pergunta} | resposta"

@app.route("/")
def home():
    cerebro = get_cerebro()
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name='viewport' content='width=device-width,initial-scale=1'><title>Alpha v6</title>
<style>body{{margin:0;background:#0e1117;color:#e6edf3;font-family:sans-serif;display:flex;flex-direction:column;height:100vh}}#chat{{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:12px}}.msg{{padding:12px;border-radius:12px;max-width:85%}}.user{{background:#238636;align-self:flex-end}}.alpha{{background:#21262d;align-self:flex-start}}#box{{display:flex;gap:8px;padding:12px;background:#161b22}}#txt{{flex:1;padding:12px;border-radius:8px;border:1px solid #30363d;background:#0d1117;color:#fff}}button{{background:#238636;color:#fff;border:none;border-radius:8px;padding:0 20px}}</style></head>
<body><div style="padding:16px;text-align:center;background:#161b22">🧠 ALPHA v6 - Memoria: {len(cerebro.get('conhecimento',{}))}</div><div id='chat'><div class='msg alpha'>Olá! Sou a Alpha! Pergunta qual meu nome 😊</div></div><div id='box'><input id='txt' placeholder='Digite...'><button onclick='enviar()'>Enviar</button></div>
<script>async function enviar(){{let i=document.getElementById('txt');let t=i.value.trim();if(!t)return;let c=document.getElementById('chat');c.innerHTML+=`<div class='msg user'>${{t}}</div>`;i.value='';let id='temp_'+Date.now();c.innerHTML+=`<div id='${{id}}' class='msg alpha'>⏳...</div>`;try{{let r=await fetch('/ask?q='+encodeURIComponent(t));let txt=await r.text();document.getElementById(id).remove();c.innerHTML+=`<div class='msg alpha'>${{txt}}</div>`;}}catch{{document.getElementById(id).remove();c.innerHTML+=`<div class='msg alpha'>Erro</div>`;}}c.scrollTop=c.scrollHeight;}}document.getElementById('txt').addEventListener('keydown',e=>{{if(e.key==='Enter')enviar();}});</script></body></html>"""

@app.route("/ask")
def ask():
    q = request.args.get("q", "")
    if q.lower().startswith("ensina:"):
        try:
            parte = q[7:].strip()
            if "|" in parte: perg,res = parte.split("|",1)
            else: perg,res = parte.split("=",1)
            cerebro = get_cerebro()
            cerebro["conhecimento"][perg.strip().lower()] = res.strip()
            salvar_cerebro(cerebro)
            return f"✅ Aprendi {perg.strip()} = {res.strip()}"
        except as e: return f"Erro use ensina: pergunta | resposta {e}"
    return responder(q)
