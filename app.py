from flask import Flask, request, jsonify, send_file, render_template
import yt_dlp, os, threading, uuid, time
from pathlib import Path
from collections import defaultdict

app = Flask(__name__)
DOWNLOAD_DIR = Path(os.path.expanduser("~/storage/dcim/VAULTDL"))
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
progress_store = {}
request_counts = defaultdict(list)
MAX_REQUESTS = 10
TIME_WINDOW = 3600

def is_rate_limited(ip):
    now = time.time()
    request_counts[ip] = [t for t in request_counts[ip] if now - t < TIME_WINDOW]
    if len(request_counts[ip]) >= MAX_REQUESTS:
        return True
    request_counts[ip].append(now)
    return False

def progress_hook(d, job_id):
    if d["status"] == "downloading":
        total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
        downloaded = d.get("downloaded_bytes", 0)
        percent = (downloaded / total * 100) if total else 0
        progress_store[job_id] = {"status":"downloading","percent":round(percent,1),"speed":d.get("_speed_str",""),"eta":d.get("_eta_str","")}
    elif d["status"] == "finished":
        progress_store[job_id] = {"status":"processing","percent":99}

def delete_later(fp):
    time.sleep(3600)
    try: os.remove(fp)
    except: pass

def do_download(url, quality, fmt, job_id):
    try:
        if fmt == "audio":
            f = "bestaudio/best"
            pp = [{"key":"FFmpegExtractAudio","preferredcodec":"mp3"}]
        else:
            q = {"best":"bestvideo+bestaudio/best","1080":"bestvideo[height<=1080]+bestaudio/best[height<=1080]/best","720":"bestvideo[height<=720]+bestaudio/best[height<=720]/best","480":"bestvideo[height<=480]+bestaudio/best[height<=480]/best"}
            f = q.get(quality,"bestvideo+bestaudio/best")
            pp = []
        out = str(DOWNLOAD_DIR / f"%(title)s_{job_id[:6]}.%(ext)s")
        opts = {"format":f,"outtmpl":out,"merge_output_format":"mp4","postprocessors":pp,"progress_hooks":[lambda d: progress_hook(d,job_id)],"noplaylist":True,"quiet":True,"cookiefile":"cookies.txt","external_downloader":"aria2c","external_downloader_args":["-x16","-s16","-k1M"]}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filepath = ydl.prepare_filename(info)
            for e in ["mp4","mkv","webm","mp3"]:
                alt = filepath.rsplit(".",1)[0]+f".{e}"
                if os.path.exists(alt): filepath=alt; break
        threading.Thread(target=delete_later, args=(filepath,), daemon=True).start()
        progress_store[job_id] = {"status":"done","percent":100,"filename":os.path.basename(filepath),"filepath":filepath,"title":info.get("title","")}
    except Exception as e:
        progress_store[job_id] = {"status":"error","error":str(e)}

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/info", methods=["POST"])
def info():
    url = request.json.get("url","").strip()
    try:
        with yt_dlp.YoutubeDL({"quiet":True}) as ydl:
            d = ydl.extract_info(url, download=False)
        return jsonify({"title":d.get("title",""),"thumbnail":d.get("thumbnail",""),"duration":d.get("duration",0),"platform":d.get("extractor_key",""),"uploader":d.get("uploader","")})
    except Exception as e:
        return jsonify({"error":str(e)}), 400

@app.route("/api/download", methods=["POST"])
def download():
    data = request.json
    ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    if is_rate_limited(ip):
        return jsonify({"error":"Limit exceed! 1 ghante mein sirf 10 downloads allowed hain."}), 429
    job_id = str(uuid.uuid4())
    progress_store[job_id] = {"status":"starting","percent":0}
    threading.Thread(target=do_download, args=(data.get("url",""),data.get("quality","best"),data.get("format","video"),job_id), daemon=True).start()
    return jsonify({"job_id":job_id})

@app.route("/api/progress/<job_id>")
def prog(job_id):
    return jsonify(progress_store.get(job_id,{"status":"not_found"}))

@app.route("/api/file/<job_id>")
def getfile(job_id):
    info = progress_store.get(job_id,{})
    fp = info.get("filepath")
    if not fp or not os.path.exists(fp):
        return jsonify({"error":"not found"}),404
    return send_file(fp, as_attachment=True)

@app.route("/static/manifest.json")
def manifest():
    return send_file("static/manifest.json", mimetype="application/manifest+json")

@app.route("/static/sw.js")
def sw():
    return send_file("static/sw.js", mimetype="application/javascript")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
