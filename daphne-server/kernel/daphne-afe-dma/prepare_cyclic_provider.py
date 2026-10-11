#!/usr/bin/env python3
"""Apply the cyclic extension to the point-3 bounded Xilinx provider.

Input is the qualified daphne_dma_bounded.c, not upstream xilinx_dma.c.
Output is a fresh directory containing source/header/Makefile; no module install.
"""
import argparse, hashlib, shutil, subprocess
from pathlib import Path
SOURCE_SHA256 = "7b0694e793756b72835c23a934b327479493bce4a1223647a87a96d7d0afea70"

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source",type=Path,help="directory of qualified bounded provider")
    ap.add_argument("output",type=Path,help="new build directory")
    args=ap.parse_args()
    src=args.source/"daphne_dma_bounded.c"
    if hashlib.sha256(src.read_bytes()).hexdigest()!=SOURCE_SHA256:
        raise SystemExit("source identity mismatch; refusing patch")
    if args.output.exists():
        raise SystemExit("output must be a new directory")
    if not (args.source/"dmaengine.h").is_file():
        raise SystemExit("missing provider dmaengine.h")
    args.output.mkdir(parents=True)
    shutil.copy2(src,args.output/src.name)
    shutil.copy2(args.source/"dmaengine.h",args.output/"dmaengine.h")
    patch=Path(__file__).with_name("cyclic-provider.patch").resolve()
    subprocess.run(["patch","--batch","--fuzz=0","-p0","-i",str(patch)],cwd=args.output,check=True)
    (args.output/"Makefile").write_text("obj-m := daphne_dma_bounded.o\n")
    print("prepared",args.output)
if __name__=="__main__": main()
