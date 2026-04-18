from fastapi import FastAPI, File, UploadFile, Form
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, ImageOps
import os
import uuid
import zipfile

app = FastAPI()

app.mount("/frontend", StaticFiles(directory="frontend"), name="frontend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = "uploads"
OUTPUT_DIR = "outputs"
ZIP_DIR = "zips"

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(ZIP_DIR, exist_ok=True)


@app.get("/")
def root():
    return {"message": "Guqula Production Optimizer running"}


# -----------------------------
# HELPERS
# -----------------------------

def has_transparency(img):
    return img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)


def fix_orientation(img):
    return ImageOps.exif_transpose(img)


def save_image(img, path, fmt):
    if fmt in ["jpg", "jpeg"]:
        if has_transparency(img):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            img = bg
        else:
            img = img.convert("RGB")

        img.save(path, "JPEG", quality=85, optimize=True, progressive=True)

    elif fmt == "webp":
        img.save(path, "WEBP", quality=80, method=6)

    elif fmt == "png":
        img.save(path, "PNG", optimize=True)


def generate_variants(img, base_name):
    paths = []

    # JPEG
    jpg_path = os.path.join(OUTPUT_DIR, f"{base_name}.jpg")
    save_image(img, jpg_path, "jpg")
    paths.append(("jpg", jpg_path, os.path.getsize(jpg_path)))

    # WEBP
    webp_path = os.path.join(OUTPUT_DIR, f"{base_name}.webp")
    save_image(img, webp_path, "webp")
    paths.append(("webp", webp_path, os.path.getsize(webp_path)))

    # PNG only if needed
    if has_transparency(img):
        png_path = os.path.join(OUTPUT_DIR, f"{base_name}.png")
        save_image(img, png_path, "png")
        paths.append(("png", png_path, os.path.getsize(png_path)))

    return paths


def pick_best(variants, original_size):
    best = min(variants, key=lambda x: x[2])

    if best[2] > original_size * 0.9:
        return variants[0]

    return best


# -----------------------------
# API
# -----------------------------

@app.post("/upload/")
async def upload_images(
    files: list[UploadFile] = File(...),
    format: str = Form("auto")
):
    results = []
    output_files = []

    for file in files:
        unique_id = str(uuid.uuid4())
        original_name = os.path.splitext(file.filename)[0]
        base_name = f"{original_name}_{unique_id}"

        input_path = os.path.join(UPLOAD_DIR, f"{base_name}_{file.filename}")

        # Save upload
        with open(input_path, "wb") as f:
            f.write(await file.read())

        original_size = os.path.getsize(input_path)

        with Image.open(input_path) as img:
            img = fix_orientation(img)

            # ---------- AUTO MODE ----------
            if format == "auto":
                variants = generate_variants(img, base_name)
                fmt, best_path, best_size = pick_best(variants, original_size)

            # ---------- MANUAL MODE ----------
            else:
                fmt = format
                output_path = os.path.join(OUTPUT_DIR, f"{base_name}.{fmt}")
                save_image(img, output_path, fmt)
                best_path = output_path
                best_size = os.path.getsize(output_path)

        output_files.append(best_path)

        results.append({
            "original_name": file.filename,
            "output_name": os.path.basename(best_path),
            "download_url": f"/download/{os.path.basename(best_path)}",
            "original_size": original_size,
            "output_size": best_size
        })

    # ---------------- ZIP CREATION ----------------
    zip_url = None

    if len(output_files) > 1:
        zip_id = str(uuid.uuid4())
        zip_path = os.path.join(ZIP_DIR, f"{zip_id}.zip")

        with zipfile.ZipFile(zip_path, "w") as zipf:
            for f in output_files:
                zipf.write(f, os.path.basename(f))

        zip_url = f"/download-zip/{zip_id}.zip"

    return {
        "message": "Optimized successfully",
        "files": results,
        "zip_url": zip_url
    }


# -----------------------------
# DOWNLOADS
# -----------------------------

@app.get("/download/{file_name}")
def download_image(file_name: str):
    file_path = os.path.join(OUTPUT_DIR, file_name)

    if not os.path.exists(file_path):
        return {"error": "File not found"}

    return FileResponse(file_path, filename=file_name)


@app.get("/download-zip/{zip_name}")
def download_zip(zip_name: str):
    zip_path = os.path.join(ZIP_DIR, zip_name)

    if not os.path.exists(zip_path):
        return {"error": "ZIP not found"}

    return FileResponse(zip_path, filename=zip_name)
