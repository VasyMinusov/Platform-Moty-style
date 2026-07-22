#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

void print_flag() {
    FILE *f = fopen("/flag.txt", "r");
    if (!f) {
        puts("[-] cannot open flag");
        return;
    }
    char flag[256];
    if (fgets(flag, sizeof(flag), f)) {
        printf("[+] FLAG: %s", flag);
    }
    fclose(f);
}

void vuln() {
    char buffer[64];
    puts("Enter your name:");
    // УЯЗВИМОСТЬ: переполнение буфера через чтение большего количества байт
    read(0, buffer, 256);
    printf("Hello, %s!\n", buffer);
}

int main() {
    setvbuf(stdout, NULL, _IONBF, 0);
    vuln();
    puts("Bye!");
    return 0;
}
