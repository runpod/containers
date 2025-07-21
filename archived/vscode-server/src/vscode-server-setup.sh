#!/bin/bash

INSTALL_LOCATION=/usr/local/bin/code-server
INSTALL_ARCH=x86_64
INSTALL_TARGET=unknown-linux-gnu

MIN_GLIBC_VERSION=2.18
LDD=$(ldd --version 2>&1)

if [ "$(uname)" = "Darwin" ]; then
  INSTALL_TARGET=apple-darwin-signed
elif echo "$LDD" | grep -q 'musl'; then
    INSTALL_TARGET=unknown-linux-musl
    echo "is musl"
else
  GLIBC_VERSION=$(echo "$LDD" | grep -o 'GLIBC [0-9]\+\.[0-9]\+' | head -n 1 | tr -d 'GLIBC ')
  echo "glibc version is $GLIBC_VERSION"
  IS_MIN_GLIBC_VERSION=$(awk 'BEGIN{ print "'$MIN_GLIBC_VERSION'"<="'$GLIBC_VERSION'" }')
  echo "is min? $IS_MIN_GLIBC_VERSION"
  if [ "$IS_MIN_GLIBC_VERSION" = "0" ]; then
    INSTALL_TARGET=unknown-linux-musl
  fi
fi

ARCH=$(uname -m)
if [ $ARCH = "aarch64" ] || [ $ARCH = "arm64" ]; then
  INSTALL_ARCH=aarch64
fi

INSTALL_URL=https://aka.ms/vscode-server-launcher/$INSTALL_ARCH-$INSTALL_TARGET
echo "Installing from $INSTALL_URL"


command_exists() {
    command -v "$1" > /dev/null 2>&1
}

download_into() {
    if command_exists curl; then
        curl -sSL "$1" -o "$2"
    elif command_exists wget; then
        wget -qO "$2" "$1"
    else
        echo "Please install curl or wget"
        exit 1
    fi
}

if command_exists curl; then
  DOWNLOAD_WITH=curl
elif command_exists wget; then
  DOWNLOAD_WITH=wget
else
  echo "Please install curl or wget"
  exit 1
fi

if command_exists sudo;
then
  if [ "$DOWNLOAD_WITH" = curl ]; then
    sudo curl -sSL "$INSTALL_URL" -o "$INSTALL_LOCATION"
  else
    sudo wget -qO "$INSTALL_LOCATION" "$INSTALL_URL"
  fi

  sudo chown $USER $INSTALL_LOCATION
else
  if [ "$DOWNLOAD_WITH" = curl ]; then
    curl -sSL "$INSTALL_URL" -o "$INSTALL_LOCATION"
  else
    wget -qO "$INSTALL_LOCATION" "$INSTALL_URL"
  fi
fi

chmod +x $INSTALL_LOCATION
