from pathlib import Path

from setuptools import find_packages, setup

with open(
    Path(__file__).parent.resolve() / "director" / "VERSION", encoding="utf-8"
) as ver:
    version = ver.readline().rstrip()

with open("requirements.txt", encoding="utf-8") as req:
    requirements = [r.rstrip() for r in req.readlines()]

long_description = ""
try:
    with open("README.md", encoding="utf-8") as readme:
        long_description = readme.read()
except FileNotFoundError:
    pass

dev_requirements = [
    "tox==3.5.3",
    "black==22.3.0",
]

doc_requirements = ["mkdocs==1.3.0", "mkdocs-material==8.2.9"]

current_dir = Path(__file__).resolve().parent  # algo-server/celery-director/
root_dir = current_dir.parent  # algo-server/
# 找到celery-director包
director_packages = find_packages(
    where=str(current_dir),
    include=["director", "director.*"]
)
# 找到workers包
workers_packages = find_packages(
    where=str(root_dir),
    include=["workers", "workers.*"]
)
all_packages = director_packages + workers_packages
# 设置包到路径的映射
package_dir = {
    "director": "director",  # director 包在 celery-director/director 中
    "workers": "../workers"  # workers 包在 ../workers中（相对于 setup.py）
}


setup(
    name="celery-director",
    version=version,
    description="Celery Director",
    long_description=long_description,
    long_description_content_type="text/markdown",
    license="BSD",
    author="OVHcloud",
    author_email="opensource@ovhcloud.com",
    url="https://github.com/ovh/celery-director",
    
    package_dir=package_dir,
    packages=all_packages,

    install_requires=requirements,
    extras_require={
        "dev": dev_requirements,
        "ci": ["pytest", "pytest-cov"],
        "doc": doc_requirements,
    },
    include_package_data=True,
    entry_points={"console_scripts": ["director=director.cli:cli"],},
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Console",
        "Environment :: Web Environment",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: BSD License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: System :: Monitoring",
    ],
    python_requires="~=3.8",
)