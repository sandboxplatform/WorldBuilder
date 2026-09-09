# WorldBuilder, deployable.
#
# The build carries web_assets/ rather than images/: 95 MB of artwork the editor
# actually references, instead of the 677 MB extracted tree. It is copied to
# images/ so every path in the JSON indexes resolves unchanged.
#
# Set WB_USER and WB_PASS, or the app is open to anyone with the URL.
# Mount a volume and point WB_MAPS/WB_OUT at it, or saves die with the container.
FROM python:3.11-slim

WORKDIR /app

# Pillow and numpy are needed by the export tools the server shells out to.
RUN pip install --no-cache-dir pillow numpy

COPY tools/ tools/
COPY editor/ editor/
COPY viewer/ viewer/
COPY catalog/ catalog/
COPY scenes/ scenes/
COPY maps/ maps/
COPY *.md ./

COPY web_assets/ images/

ENV WB_MAPS=/data/maps \
    WB_OUT=/data/out \
    PYTHONUNBUFFERED=1
EXPOSE 8823

CMD ["python3", "tools/serve.py"]
