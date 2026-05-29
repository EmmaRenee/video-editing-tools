"""
Setup script for videoedit package.

Installation:
    pip install -e .
"""
import os

from setuptools import setup, find_packages

with open(os.path.join(os.path.dirname(__file__), "README.md"), encoding="utf-8") as handle:
    README = handle.read()

setup(
    name="videoedit",
    version="0.5.0",
    description="AI-first video editing pipeline system",
    long_description=README,
    long_description_content_type="text/markdown",
    url="https://github.com/EmmaRenee/video-editing-tools",
    author="Emma Werner",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[],
    extras_require={
        "whisper": ["openai-whisper>=20231117"],
        "advanced": ["opencv-python>=4.8.0", "ultralytics>=8.0.0"],
        "cloud": ["elevenlabs", "python-dotenv"],
        "ui": ["textual>=0.50.0", "rich>=13.0.0"],
    },
    entry_points={
        "console_scripts": [
            "videoedit=videoedit.cli:main",
        ],
    },
    python_requires=">=3.10",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
)
