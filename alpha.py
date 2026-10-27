import os
import re
import difflib
import logging
import urllib.parse
from typing import Optional
import requests
from flask import Flask, jsonify, request, render_template_string

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024
logging.basicConfig(level=logging.INFO)

FB = os.environ.get("FIREBASE_DATABASE_URL","https://alpha-98bb1-default-rtdb.firebaseio.com").rstrip("/")
TIMEOUT = 8
MAX_MEMORY_ITEMS = 300
MAX_MESSAGE_CHARS = 2000
MAX_CONTEXT_MESSAGES = 12

AI_API_KEY = os.environ.get("AI_API_KEY", "")
AI_BASE_URL = os.environ.get("AI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
AI_MODEL = os.environ.get("AI_MODEL", "")
AI_ENABLED = bool(AI_API_KEY and AI_MODEL)

HTML = r"""<!doctype html><html lang="pt"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AlphAI ULTRA</title>
<style>:root{--bg:#080d18;--panel:#101827;--line:#26334a;--text:#eef4ff;--muted:#9aabc5}*{box-sizing:border-box}body{margin:0;background:#080d18;color:var(--text);font:15px/1.5 system-ui;display:flex;height:100dvh;overflow:hidden}
.sidebar{width:260px;border-right:1px solid var(--line);padding:18px;display:flex;flex-direction:column;gap:14px}.main{flex:1;display:flex;flex-direction:column}.topbar{height:64px;border-bottom:1px solid var(--line);display:flex;align-items:center;padding:0 22px}.chat{max-width:900px;margin:0 auto;flex:1;overflow:auto;padding:22px;width:100%}.msg{display:flex;gap:10px;margin:14px 0}.msg.user{flex-direction:row-reverse}.content{padding:12px 16px;border:1px solid var(--line);background:#111b2a;border-radius:14px;max-width:80%;white-space:pre-wrap}.user .content{background:#1e40af}.composer{max-width:900px;margin:0 auto;display:flex;gap:8px;padding:12px;border:1px solid var(--line);background:#101827;border-radius:16px;margin-bottom:12px}textarea{flex:1;background:transparent;border:0;color:#fff;outline:0;resize:none}button{background:#3b82f6;color:#fff;border:0;border-radius:10px;padding:10px 16px;font-weight:700;cursor:pointer}
</style></head><body>
<aside class="sidebar"><b>AlphAI ULTRA</b><button id="newChat">+ Nova conversa</button><div id="history"></div></aside>
<main class="main"><div class="topbar">Centro de comando - ULTRA</div><section class="chat" id="chat"><div id="messages"></div></section><form class="composer" id="form"><textarea id="prompt" placeholder="Escreve aqui..."></textarea><button type="submit">Enviar</button></form></main>
<script>
const STORAGE_KEY='alphai_v1';let conversations=JSON.parse(localStorage.getItem(STORAGE_KEY)||'[]');let activeId=conversations[0]?.id||null;
function save(){localStorage.setItem(STORAGE_KEY,JSON.stringify(conversations.slice(0,50)))}
function render(){const box=document.getElementById('messages');box.innerHTML='';const c=conversations.find(x=>x.id===activeId);if(!c)return;c.messages.forEach(m=>{box.innerHTML+=`<div class="msg ${m.role}"><div class="content">${m.text}${m.image_url?`<br><img src="${m.image_url}" style="max-width:100%;border-radius:12px;margin-top:8px">`:''}</div></div>`})}
async function sendMessage(t){t=t||document.getElementById('prompt').value.trim();if(!t)return;if(!activeId){const id=Date.now().toString();conversations.unshift({id,title:t.slice(0,30),messages:[]});activeId=id}const c=conversations.find(x=>x.id===activeId);c.messages.push({role:'user',text:t});document.getElementById('prompt').value='';render();save();const r=await fetch('/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({q:t})});const d=await r.json();c.messages.push({role:'assistant',text:d.text,image_url:d.image_url});render();save()}
document.getElementById('form').addEventListener('submit',e=>{e.preventDefault();sendMessage()});document.getElementById('newChat').onclick=()=>{const id=Date.now().toString();conversations.unshift({id,title:'Nova',messages:[]});activeId=id;save();render()};if(conversations.length)render();
</script></body></html>
"""

def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()

def is_greeting(text: str) -> bool:
    t = re.sub(r"[!.,?…]+$", "", normalize(text))
    return t in {"ola","olá","oi","hey","hi","bom dia","boa tarde","boa noite"}

def image_prompt(text: str) -> Optional[str]:
    low = text.casefold()
    triggers = ("gera imagem de","gerar imagem de","cria imagem de","crie imagem de","imagem de","desenha","faz imagem de")
    for tr in triggers:
        if tr in low:
            p = text[low.find(tr)+len(tr):].strip(" :,-.")
            if len(p)>=2: return p[:500]
    return None

def make_image_url(prompt: str) -> str:
    enc = urllib.parse.quote(prompt, safe="")
    return f"https://image.pollinations.ai/prompt/{enc}?width=1024&height=1024&nologo=true&enhance=true"

def firebase_get_memory():
    try:
        r = requests.get(f"{FB}/memoria.json", params={"orderBy":'"$key"',"limitToLast":str(MAX_MEMORY_ITEMS)}, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json() or {}
        items=[]
        for k,v in data.items():
            if isinstance(v,dict) and v.get("original") and v.get("resposta"):
                items.append({"original":str(v["original"])[:500],"resposta":str(v["resposta"])[:5000]})
        return items
    except: return []

def find_memory(query: str, items: list) -> Optional[str]:
    q = normalize(query)
    originals = [normalize(i["original"]) for i in items]
    for i,o in enumerate(originals):
        if q==o: return items[i]["resposta"]
    m = difflib.get_close_matches(q, originals, n=1, cutoff=0.86)
    if m: return items[originals.index(m[0])]["resposta"]
    return None

def search_wikipedia(query: str):
    clean = re.sub(r"^(o que é|quem é|explica)\s+","",query.strip(),flags=re.I)
    if len(clean)<2: return None
    url = "https://pt.wikipedia.org/api/rest_v1/page/summary/"+urllib.parse.quote(clean[:100])
    try:
        r = requests.get(url, timeout=TIMEOUT, headers={"User-Agent":"AlphAI/1.0"})
        if r.status_code!=200: return None
        d=r.json()
        if d.get("extract"):
            return {"text":d["extract"][:1800],"sources":[{"title":"Wikipedia","url":d.get("content_urls",{}).get("desktop",{}).get("page") or url}]}
    except: return None
    return None

def answer_message(payload: dict):
    raw = payload.get("q","")
    if not isinstance(raw,str): return {"text":"Mensagem deve ser texto.","sources":[]},400
    raw=raw.strip()
    if not raw: return {"text":"Escreve uma mensagem.","sources":[]},400
    if len(raw)>MAX_MESSAGE_CHARS: return {"text":f"Mensagem muito longa. Max {MAX_MESSAGE_CHARS}.","sources":[]},400

    if is_greeting(raw):
        return {"text":"Olá! Sou a AlphAI ULTRA 🚀 Como posso ajudar?","sources":[]}

    # Imagem
    ip = image_prompt(raw)
    if ip:
        return {"text":f"Imagem gerada: {ip}","image_url":make_image_url(ip),"prompt":ip,"sources":[]}

    # Memoria Firebase
    mem = firebase_get_memory()
    fm = find_memory(raw, mem)
    if fm:
        return {"text":fm,"sources":[]}

    # Wikipedia
    wiki = search_wikipedia(raw)
    if wiki:
        return {"text":wiki["text"],"sources":wiki["sources"]}

    # Fallback
    return {"text":f"Entendi: '{raw}'. Ainda estou aprendendo sobre isso. Podes me ensinar a resposta ideal?","sources":[]}

@app.route("/")
def home():
    return render_template_string(HTML)

@app.route("/ask", methods=["POST"])
def ask():
    data = request.get_json(silent=True) or {}
    result = answer_message(data)
    if isinstance(result,tuple):
        body,code = result
        return jsonify(body),code
    return jsonify(result)

@app.route("/api/chat")
def api_chat():
    result = answer_message(request.args.to_dict())
    if isinstance(result,tuple):
        body,code = result
        return jsonify(body),code
    return jsonify(result)

if __name__ == "__main__":
    port = int(os.environ.get("PORT",5000))
    print(f"AlphAI ULTRA rodando em http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, debug=True)
