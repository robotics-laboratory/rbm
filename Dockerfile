# https://hub.docker.com/layers/library/ros/jazzy-ros-base
FROM ros:jazzy-ros-base@sha256:066420e07f60aa18262f2479981def87ebcfcec42eefb0c0c57c4a46098348ca

ENV ROS_VERSION=2
ENV ROS_DISTRO=jazzy
ENV ROS_ROOT=/opt/ros/$ROS_DISTRO
ENV RCUTILS_LOGGING_BUFFERED_STREAM=1
ENV RCUTILS_COLORIZED_OUTPUT=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PIP_ROOT_USER_ACTION=ignore
ENV CMAKE_BUILD_TYPE=Release
ENV DEBIAN_FRONTEND=noninteractive

# --no-install-recommends
RUN echo '\
APT::Install-Recommends "0";\n\
APT::Install-Suggests "0";\n\
' > /etc/apt/apt.conf.d/01-no-recommends

# Install cyclonedds RMW
ENV RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
RUN apt update && \
    apt install -y ros-$ROS_DISTRO-rmw-cyclonedds-cpp && \
    rm -rf /var/lib/apt/lists/*

# Install foxglove bridge v0.8.5
RUN . $ROS_ROOT/setup.sh \
    && mkdir /tmp/foxglove-build \
    && cd /tmp/foxglove-build \
    && mkdir src \
    && echo "\
    - git:\n\
        local-name: foxglove-sdk/foxglove_bridge\n\
        uri: https://github.com/ros2-gbp/foxglove_bridge-release.git\n\
        version: release/$ROS_DISTRO/foxglove_bridge/0.8.5-1\n\
    " | vcs import src \
    && apt update \
    && rosdep install --from-paths src --ignore-src -y \
    && colcon build --merge-install --install-base /opt/ros/$ROS_DISTRO \
    --cmake-args -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF \
    && rm -rf /tmp/* \
    && rm -rf /var/lib/apt/lists/*

# Install Nav2 dependencies
RUN apt update && \
    apt install -y \
    ros-$ROS_DISTRO-nav2-core \
    ros-$ROS_DISTRO-nav2-controller \
    ros-$ROS_DISTRO-nav2-bt-navigator \
    ros-$ROS_DISTRO-nav2-lifecycle-manager \
    ros-$ROS_DISTRO-nav2-behaviors \
    ros-$ROS_DISTRO-nav2-planner \
    ros-$ROS_DISTRO-nav2-navfn-planner \
    ros-$ROS_DISTRO-nav2-regulated-pure-pursuit-controller \
    ros-$ROS_DISTRO-nav2-loopback-sim \
    ros-$ROS_DISTRO-nav2-map-server \
    && rm -rf /var/lib/apt/lists/*

# Install slam toolbox with patch
WORKDIR /tmp/slam-toolbox-build
ADD docker/slam-toolbox.patch .
RUN . $ROS_ROOT/setup.sh \
    && mkdir src \
    && echo "\
    - git:\n\
        local-name: slam_toolbox\n\
        uri: https://github.com/SteveMacenski/slam_toolbox-release.git\n\
        version: release/jazzy/slam_toolbox/2.8.3-1\n\
    " | vcs import src \
    && (cd src/slam_toolbox && git apply ../../slam-toolbox.patch) \
    && apt update \
    && rosdep install --from-paths src --ignore-src -y \
    && colcon build --merge-install --install-base /opt/ros/$ROS_DISTRO \
    --cmake-args -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF \
    && rm -rf /tmp/* \
    && rm -rf /var/lib/apt/lists/*

# Patch nav2 loopback simulator
WORKDIR /tmp/nav2-loopback-sim-patch
ADD docker/nav2-loopback-sim.patch .
RUN patch -p1 -i nav2-loopback-sim.patch \
    $(find /opt/ros/$ROS_DISTRO -name loopback_simulator.py)

# Install LD19 lidar driver with patch
WORKDIR /tmp/ld19-lidar-build
ADD docker/ld19-lidar.patch .
RUN . $ROS_ROOT/setup.sh \
    && mkdir src \
    && git clone https://github.com/richardw347/ld19_lidar src/ld19_lidar \
    && (cd src/ld19_lidar && git apply ../../ld19-lidar.patch) \
    && colcon build --merge-install --install-base /opt/ros/$ROS_DISTRO \
    --cmake-args -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF \
    && rm -rf /tmp/*

# Install extra ROS dependencies
RUN apt update && \
    apt install -y \
    ros-$ROS_DISTRO-xacro \
    ros-$ROS_DISTRO-robot-state-publisher \
    ros-$ROS_DISTRO-robot-localization \
    && rm -rf /var/lib/apt/lists/*

# Install rtabmap-odom
RUN apt update && \
    apt install -y ros-$ROS_DISTRO-rtabmap-odom \
    && export MARCH=$(gcc -dumpmachine) \
    && rm -rf /usr/lib/$MARCH/libLLVM* \
    && rm -rf /usr/lib/$MARCH/libgallium* \
    && rm -rf /usr/lib/$MARCH/libQt* \
    && rm -rf /usr/lib/$MARCH/libclang* \
    && rm -rf /usr/lib/$MARCH/java \
    && rm -rf /usr/lib/jvm \
    && rm -rf /usr/lib/llvm* \
    && rm -rf /usr/lib/qt5 \
    && rm -rf /usr/share/doc \
    && rm -rf /usr/share/icons \
    && rm -rf /var/lib/apt/lists/*

# Install extra tools
RUN apt update && \
    apt install -y \
    tmux \
    tmuxp \
    nano \
    wget \
    python3-pip \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Setup python venv
RUN python3 -m venv /root/venv --system-site-packages \
    && . /root/venv/bin/activate \
    && pip install pyserial cobs anycrc

# Setup Jupyter Lab
RUN . /root/venv/bin/activate \
    && pip install jupyterlab \
    && mkdir -p /root/venv/share/jupyter/lab/settings \
    && echo '{"@jupyterlab/apputils-extension:themes": {"theme": "JupyterLab Dark"}}' \
    > /root/venv/share/jupyter/lab/settings/overrides.json \
    && mkdir -p /root/.jupyter \
    && echo '\
c = get_config()\n\
c.ServerApp.allow_root = True\n\
c.ServerApp.ip = "0.0.0.0"\n\
c.ServerApp.port = 8080\n\
c.ServerApp.open_browser = False\n\
c.ServerApp.token = ""\n\
c.ServerApp.password = ""\n\
    ' > /root/.jupyter/jupyter_lab_config.py

# Fix setuptools version
# https://github.com/ros2/ros2/issues/1702
# https://github.com/ros2/ros2/issues/1094
RUN . /root/venv/bin/activate && pip install "setuptools<80.0.0"

# Setup mediamtx
# Mediamtx bre-built custom binary is downloaded from S3
# Built from tag v1.18.1 with docker/mediamtx.patch applied
# https://github.com/bluenviron/mediamtx/issues/5744
RUN wget -O /bin/mediamtx https://storage.yandexcloud.net/the-lab-storage/rbm/mediamtx-1.18.1-arm64-patched \
    && chmod +x /bin/mediamtx

# Install gstreamer + pre-built custom plugin
RUN apt update && \
    apt install -y \
    gstreamer1.0-tools \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-rtsp \
    && wget -P /usr/lib/$(gcc -dumpmachine)/gstreamer-1.0 https://storage.yandexcloud.net/the-lab-storage/rbm/libgsthoboth264.so \
    && rm -rf /var/lib/apt/lists/*

# Install openvscode
ARG OPENVSCODE_DOWNLOAD_URL="https://github.com/gitpod-io/openvscode-server/releases/download/openvscode-server-v1.109.5/openvscode-server-v1.109.5-linux-arm64.tar.gz"
ARG OPENVSCODE_ROOT="/opt/openvscode-server"
ENV PATH="${PATH}:${OPENVSCODE_ROOT}/bin"
RUN mkdir ${OPENVSCODE_ROOT} && curl -sSL "${OPENVSCODE_DOWNLOAD_URL}" | tar -xz -C ${OPENVSCODE_ROOT} --strip-components=1
RUN mkdir -p /root/.openvscode-server/data/Machine && echo '{\n\
    "workbench.colorTheme": "Default Dark Modern",\n\
    "files.dialog.defaultPath": "/src",\n\
    "python.languageServer": "Jedi",\n\
}' >> /root/.openvscode-server/data/Machine/settings.json
RUN mkdir -p /tmp/extensions && cd /tmp/extensions \
    && curl -sSL -O https://github.com/spkane/vscode-training-tweaks/releases/download/v0.0.3/training-tweaks-0.0.3.vsix \
    && openvscode-server --install-extension /tmp/extensions/* \
    && openvscode-server --install-extension ms-python.python \
    && openvscode-server --install-extension ms-python.black-formatter

# Setup .bashrc
RUN echo '\
export LD_LIBRARY_PATH=$ROS_ROOT/lib/$(gcc -dumpmachine):/usr/local/lib/$(gcc -dumpmachine):/usr/hobot/lib\n\
source $ROS_ROOT/setup.bash\n\
LOCAL_SETUP="/src/install/setup.bash";\n\
if [ -f "$LOCAL_SETUP" ]; then source $LOCAL_SETUP; fi\n\
source /root/venv/bin/activate\n\
' >> /root/.bashrc

# Entrypoint
WORKDIR /src
ENTRYPOINT ["/bin/bash", "-lc"]
CMD ["trap : TERM INT; sleep infinity & wait"]
