FROM ubuntu:16.04

ENV USER root
ENV DEBIAN_FRONTEND noninteractive
ENV TZ 'Europe/Moscow'

ARG API_DOWNLOAD_URL=http://build.swifttest.com:8080/job/API_MAIN_Combo/lastSuccessfulBuild/artifact/dist/*zip*/dist.zip

ARG APP_HOME=/usr/src/apitest
ARG PACKAGES='gcc python python-dev mono-complete unzip curl'

WORKDIR $APP_HOME

# isntall python and mono
RUN apt-key adv --keyserver hkp://keyserver.ubuntu.com:80 --recv-keys 3FA7E0328081BFF6A14DA29AA6A19B38D3D831EF && \
  echo "deb http://download.mono-project.com/repo/debian wheezy main" > /etc/apt/sources.list.d/mono-xamarin.list && \
  apt-get update && \
  apt-get install -y --no-install-recommends $PACKAGES && \
  apt-get clean

# install API
ADD $API_DOWNLOAD_URL /tmp

RUN unzip /tmp/dist.zip -d /tmp && \
  cd /tmp/dist/* && \
  yes | ./install_api -y && \
  apt-get remove -y --purge unzip curl && \
  rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

COPY . $APP_HOME

VOLUME /opt/swifttest/resources/dotnet/Ports

CMD ["python", "-u", "test.py", "-h"]
