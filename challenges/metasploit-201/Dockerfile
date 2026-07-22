FROM tomcat:9.0-jdk11-temurin

ARG FLAG=flag{m3t4spl01t_t0mc4t_mgr_0wn3d}
ENV FLAG=$FLAG

# Кладём флаг, который нужно прочитать через shell
RUN echo "$FLAG" > /flag.txt && chmod 644 /flag.txt

# В современных образах manager и host-manager находятся в webapps.dist
# СНАЧАЛА создаём папку webapps, иначе cp создаст ФАЙЛ вместо папки!
RUN mkdir -p /usr/local/tomcat/webapps \
    && cp -r /usr/local/tomcat/webapps.dist/manager /usr/local/tomcat/webapps/ \
    && cp -r /usr/local/tomcat/webapps.dist/host-manager /usr/local/tomcat/webapps/

# Разрешаем доступ к manager/host-manager извне (не только с localhost)
COPY manager-context.xml /usr/local/tomcat/webapps/manager/META-INF/context.xml
COPY host-manager-context.xml /usr/local/tomcat/webapps/host-manager/META-INF/context.xml

# Создаём пользователя tomcat со слабым паролем
COPY tomcat-users.xml /usr/local/tomcat/conf/tomcat-users.xml

# Перенаправляем порт Tomcat с 8080 на 5000 (container_port в манифесте)
RUN sed -i 's/Connector port="8080"/Connector port="5000"/' /usr/local/tomcat/conf/server.xml

EXPOSE 5000

CMD ["catalina.sh", "run"]
