# Stage 1: Build OpenCV
FROM alpine:3.19 AS opencv-builder

# Install build dependencies
RUN apk add --no-cache \
    build-base \
    cmake \
    git \
    python3-dev \
    py3-pip \
    libjpeg-turbo-dev \
    libpng-dev \
    libwebp-dev \
    tiff-dev \
    openblas-dev \
    linux-headers \
    gfortran \
    musl-dev

# Set environment variables
ENV OPENCV_VERSION=4.8.0
ENV BUILD_DIR=/tmp/opencv-build

# Clone OpenCV and OpenCV contrib repositories
RUN mkdir -p $BUILD_DIR && \
    git clone --depth 1 --branch $OPENCV_VERSION https://github.com/opencv/opencv.git $BUILD_DIR/opencv && \
    git clone --depth 1 --branch $OPENCV_VERSION https://github.com/opencv/opencv_contrib.git $BUILD_DIR/opencv_contrib

# Build OpenCV
# -D WITH_IPP=OFF -> Disable Intel IPP to build on aarch64
RUN cd $BUILD_DIR/opencv && \
    mkdir build && cd build && \
    cmake \
        -D CMAKE_BUILD_TYPE=Release \
        -D CMAKE_INSTALL_PREFIX=/usr/local \
        -D OPENCV_EXTRA_MODULES_PATH=$BUILD_DIR/opencv_contrib/modules \
        -D BUILD_EXAMPLES=OFF \
        -D BUILD_TESTS=OFF \
        -D BUILD_DOCS=OFF \
        -D BUILD_PERF_TESTS=OFF \
        -D BUILD_JAVA=OFF \
        -D WITH_TBB=OFF \
        -D WITH_OPENMP=ON \
        -D WITH_IPP=OFF \
        -D WITH_LAPACK=ON \
        -D WITH_EIGEN=ON \
        -D BUILD_SHARED_LIBS=ON \
        .. && \
    make -j$(nproc) && \
    make install


FROM python:3.10-alpine3.19 AS app-builder

RUN apk add --no-cache \
    build-base \
    cmake \
    git \
    linux-headers

# Slow build, should run seperate to prevent rebuilding when requirements.txt is updated
RUN CMAKE_BUILD_PARALLEL_LEVEL=$(nproc) pip install --no-cache-dir opencv-python==4.10.0.84

COPY ./requirements.txt ./
RUN CMAKE_BUILD_PARALLEL_LEVEL=$(nproc) pip install --no-cache-dir -r ./requirements.txt


# Build tesseract for OCR
#FROM quocbao747/alpine-tesseract:3.13-5.5.0 AS tesseract-builder
FROM alpine:3.19 AS tesseract-builder

WORKDIR /build

RUN apk add --update --no-cache libtool automake autoconf pkgconfig g++ make leptonica-dev && \
    wget https://github.com/tesseract-ocr/tesseract/archive/refs/tags/5.5.0.tar.gz && \
    tar -xvzf 5.5.0.tar.gz && \
    cd tesseract-5.5.0 && \
    ./autogen.sh && \
    LIBLEPT_HEADERSDIR=/usr/local/include  ./configure --enable-static --disable-shared --with-extra-libraries=/usr/local/lib && \
    LDFLAGS="-static" make -j $(nproc) && \
    make install

RUN wget https://github.com/tesseract-ocr/tessdata/raw/refs/heads/main/eng.traineddata -O /build/eng.traineddata
RUN wget https://github.com/tesseract-ocr/tessdata/raw/refs/heads/main/vie.traineddata -O /build/vie.traineddata




# Stage 2: Create final image
FROM python:3.10-alpine3.19

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Copy OpenCV from builder stage
COPY --from=opencv-builder /usr/local /usr/local

# Copy tesseract
ENV TESSDATA_PREFIX /usr/local/share/tessdata
COPY --from=tesseract-builder /usr/local/bin/tesseract /usr/local/bin/tesseract
COPY --from=tesseract-builder /usr/local/share/tessdata /usr/local/share/tessdata
COPY --from=tesseract-builder /build/eng.traineddata /usr/local/share/tessdata/eng.traineddata
COPY --from=tesseract-builder /build/vie.traineddata /usr/local/share/tessdata/vie.traineddata

RUN apk add --update --no-cache \
    leptonica-dev \
    libgomp tiff-dev \
    libjpeg-turbo \
    libpng

# Copy app
COPY --from=app-builder /usr/local/bin/gunicorn /usr/local/bin/gunicorn
COPY --from=app-builder /usr/local/lib/python3.10/site-packages/ /usr/local/lib/python3.10/site-packages/

ADD models /app/models
ADD utils /app/utils
COPY *.py /app

CMD [ "gunicorn", "--timeout", "3600", "--limit-request-line", "16384", "--access-logfile", "-", "-c", "config.py", "wsgi:screenberry"]