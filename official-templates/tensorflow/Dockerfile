FROM tensorflow/tensorflow:latest-gpu-jupyter

RUN pip install jupyter_contrib_nbextensions notebook
RUN jupyter contrib nbextension install --user && \
    jupyter nbextension enable --py widgetsnbextension


# NGINX Proxy
COPY --from=proxy nginx.conf /etc/nginx/nginx.conf
COPY --from=proxy readme.html /usr/share/nginx/html/readme.html

# Copy the README.md
COPY README.md /usr/share/nginx/html/README.md

# Start Scripts
COPY --from=scripts start.sh /
RUN chmod +x /start.sh

# Set the default command for the container
CMD [ "/start.sh" ]
