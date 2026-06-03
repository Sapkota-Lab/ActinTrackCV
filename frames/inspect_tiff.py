import tifffile, numpy as np
from PIL import Image
stack = tifffile.imread("1_WT_218/01.tif")
for c in [0, 1]:
    img = stack[7, c]  # middle slice, both channels
    img_8 = (255 * (img.astype(float) - img.min()) / (np.ptp(img) + 1e-9)).astype(np.uint8)
    Image.fromarray(img_8).save(f"middle_ch{c}.png")