# CyTrack

This is a personal 

![Version](https://img.shields.io/badge/version-1.0-green)

A lightweight confluency tracker for both cell line and organoid cultures. Upload brightfield images, get automated segmentation and confluency measurements, and track proliferation dynamics across passage cycles over time. Built for lab teams or individuals, host it on a shared server or a shared PC and uses can review cultures from their browser.

I designed this as an experiment to get familiar with Claude Code over a weekend (https://code.claude.com/). Both the Opus 4.6 (for complex tasks) and Sonnet 4.6 models (for simple design tasks) were used throughout the project. CyTrack was written with the Dash python framework (https://dash.plotly.com/) as I was already familiar with the tool. The Cellpose "Cyto3" model is also used to segment images by default (https://github.com/mouseland/cellpose).


## Features
- **Segmentation** - Use either Cellpose (deep learning) or Otsu (traditional thresholding).
- **Confluency tracking** - Confluency plots with passage annotations and colour-coded proliferation cycles
- **Logging** - View per-passage growth status, compare proliferation dynamics
- **Cell lines & organoids** - works with any brightfield culture imaging workflow
- **Measurement log** - full history with date, passage, confluency, segmentation method, and delta tracking
- **Image review** - raw, mask overlay, and cell outline views for every measurement
- **Editable records** - correct dates, passages, or replace images after the fact
- **File-based storage** - each culture is a self-contained folder, easy to back up or share
- **Multi-user ready** - host on a shared machine or host on a server and access from anywhere


![CyTrack Screenshot](assets/app-demo.png)



## Install
```bash
# Clone with git and change into a new directory 
git clone https://github.com/charliebidgood/CyTrack
cd CyTrack

# Recommended: Create a new conda environment
conda create -n cytrack python=3.10

# Activate, you may need to use "source activate" in some cases
conda activate cytrack

# Install the required python dependencies
pip install -r requirements.txt

# Run - debug mode is turned off by default
python app.py
```

For development and single-user use you can open **http://localhost:8050** in your browser. If this doesn't work check the terminal output for the correct port. 

To run as an accessible server you can use a service like https://render.com/ or https://www.heroku.com/ or run internally on your network.

Quick note: CyTrack is a personal side project which I built in my own time with my own resources, and isn't connected to my employer in any way. Just sharing something I found useful and thought others in the community might too!

Important: this tool is not designed for sensitive or proprietary data. Before using it, please check your own institution's data policies. If your data is sensitive, regulated, or commercially confidential, please do not use CyTrack until you've confirmed it's appropriate to do so.

## Requirements

- Python 3.9+, dash, plotly, numpy, Pillow 
- Cellpose (recommended) — falls back to Otsu thresholding if not installed

## Tips
- **Confluency** - For most cell lines, 70-80% by cellpose segmentation  is what many would call 100% confluent when measuring by eye (in my experience)
- **Segmentation** - Cellpose is computationally draining, particularly if you do not have access to a GPU. Otsu is extremely fast even when running on CPU but may perform poorly on brightfield images. Otsu tends to perform poorly for very dense or sparse cultures from brightfield, I've found cellpose to work better in these instances.



This project was built with the assistance of [Claude Code](https://claude.ai) by Anthropic.
