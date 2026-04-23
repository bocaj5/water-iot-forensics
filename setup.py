#!/usr/bin/env python3
"""
Setup script for Water Treatment IoT Forensic System - Dual Pi Version
"""

from setuptools import setup, find_packages

setup(
    name='water-iot-forensics-dual-pi',
    version='2.0.0',
    description='Water Treatment IoT Forensic System using Dual Raspberry Pi 4s',
    author='Your Name',
    author_email='your.email@example.com',
    url='https://github.com/yourusername/water-iot-forensics',

    packages=find_packages(),

    install_requires=[
        'RPi.GPIO>=0.7.0',
        'gpiozero>=1.6.2',
        'aiocoap>=0.4.3',
        'cryptography>=3.4.6',
        'numpy>=1.21.0',
        'pandas>=1.3.0',
        'scikit-learn>=0.24.2',
        'python-dotenv>=0.19.0',
    ],

    extras_require={
        'pi2': [
            'tensorflow-lite>=2.6.0',
            'sqlalchemy>=1.4.0',
        ],
        'dev': [
            'pytest>=6.2.4',
            'pytest-asyncio>=0.18.0',
        ]
    },

    python_requires='>=3.8',

    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
    ],
)
