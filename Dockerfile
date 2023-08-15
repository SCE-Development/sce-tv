FROM python:3.10.2-slim-buster

WORKDIR /service

RUN apt-get update && apt-get install -y ffmpeg git

COPY requirements.txt /service

RUN pip3 install git+https://github.com/joejztang/pytube.git@499268313ada0b971dc5b6718986b27d97731f05

RUN pip3 install -r /service/requirements.txt

COPY static/ /service/static/

COPY *.py .

EXPOSE 5001

STOPSIGNAL SIGINT

ENTRYPOINT ["python","api.py"]
