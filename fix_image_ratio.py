from PIL import Image
import os

img_path = 'theme/system.png'
img = Image.open(img_path)
width, height = img.size
target_ratio = 4/3

# Center crop to 4:3
new_height = int(width / target_ratio)
top = (height - new_height) // 2
img = img.crop((0, top, width, top + new_height))

# Resize to integer multiple of 640x480
img = img.resize((1280, 960), Image.Resampling.LANCZOS)
img.save(img_path)
print(f"Successfully resized {img_path} to {img.size}")
