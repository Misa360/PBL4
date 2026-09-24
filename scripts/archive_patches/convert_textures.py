"""
Convert 8k_earth_normal_map.tif  → 8k_earth_normal_map.png
       8k_earth_specular_map.tif → 8k_earth_specular_map.jpg
Chạy một lần duy nhất từ thư mục PBL4.
"""
import os, sys
os.environ['PYTHONIOENCODING'] = 'utf-8'

from PIL import Image

TEXTURE_DIR = 'texture'

def convert(src_name, dst_name, mode=None, quality=90):
    src = os.path.join(TEXTURE_DIR, src_name)
    dst = os.path.join(TEXTURE_DIR, dst_name)
    if not os.path.exists(src):
        print(f'[SKIP] Khong tim thay: {src}')
        return
    if os.path.exists(dst):
        print(f'[SKIP] Da ton tai: {dst}')
        return
    print(f'[CONVERT] {src} -> {dst} ...')
    img = Image.open(src)
    if mode:
        img = img.convert(mode)
    save_kwargs = {}
    if dst.endswith('.jpg'):
        save_kwargs['quality'] = quality
        save_kwargs['optimize'] = True
        img = img.convert('RGB')
    img.save(dst, **save_kwargs)
    size_mb = os.path.getsize(dst) / 1024 / 1024
    print(f'  Xong! Kich thuoc: {size_mb:.1f} MB')

# Normal map: giữ nguyên mode (RGB/L), lưu PNG không mất dữ liệu
convert('8k_earth_normal_map.tif', '8k_earth_normal_map.png')

# Specular map: greyscale -> JPG
convert('8k_earth_specular_map.tif', '8k_earth_specular_map.jpg', mode='L', quality=90)

print('\nHoan thanh convert texture!')
