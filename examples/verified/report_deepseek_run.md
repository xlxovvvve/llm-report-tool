# 实验报告草稿（LLM 生成 + 规则校验）

> 自动校验：检查 9 个步骤，通过 9 个，ERROR 0 条，WARNING 0 条
> 标记 `!!` 的步骤存在待确认问题，需人工核对原始终端日志。

## [OK] 步骤 1：创建实验目录

**命令**

```bash
sudo mkdir -p /root/wht+OtherHeadFiles /root/wht+OtherLibs && sudo chown -R wht:wht /root/wht+OtherHeadFiles /root/wht+OtherLibs && ls -ld /root/wht+OtherHeadFiles /root/wht+OtherLibs
```

**含义**：创建了两个目录 /root/wht+OtherHeadFiles 和 /root/wht+OtherLibs，并将它们的所有者改为用户 wht，然后列出目录的详细信息确认创建成功。

**结果**：两个目录都已创建，所有者均为 wht，权限为 drwxr-xr-x。

**真实输出**

```
drwxr-xr-x. 2 wht wht 21 Oct 24 02:01 /root/wht+OtherHeadFiles
drwxr-xr-x. 2 wht wht 23 Oct 24 02:06 /root/wht+OtherLibs
```

## [OK] 步骤 2：查看头文件 MyLib.h

**命令**

```bash
cat /root/wht+OtherHeadFiles/MyLib.h
```

**含义**：查看了头文件 MyLib.h 的内容，其中声明了函数 add。

**结果**：头文件包含防止重复包含的宏定义，并声明了 int add(int, int); 函数。

**真实输出**

```
#ifndef _MYLIB_H_
#define _MYLIB_H_
int add(int, int);
#endif
```

## [OK] 步骤 3：编译生成动态库 libadd.so

**命令**

```bash
cd /root/wht && gcc -fPIC -shared -I../wht+OtherHeadFiles/ -o libadd.so add.c && ls -l libadd.so && file libadd.so
```

**含义**：使用 gcc 编译 add.c 生成动态库 libadd.so，并查看文件信息和类型。

**结果**：成功生成 libadd.so，它是一个 64 位 ELF 共享库文件。

**真实输出**

```
-rwxr-xr-x. 1 wht wht 7880 Oct 24 02:11 libadd.so
libadd.so: ELF 64-bit LSB shared object, x86-64, version 1 (SYSV), dynamically linked, not stripped
```

## [OK] 步骤 4：链接生成可执行程序 Compute

**命令**

```bash
cd /root/wht && gcc Compute.c -o Compute -I../wht+OtherHeadFiles/ -L../wht+OtherLibs/ -ladd && ls -l Compute && file Compute
```

**含义**：将 Compute.c 与动态库 libadd.so 链接，生成可执行程序 Compute，并查看文件信息和类型。

**结果**：成功生成可执行文件 Compute，它是一个 64 位 ELF 可执行文件，动态链接。

**真实输出**

```
-rwxr-xr-x. 1 wht wht 8400 Oct 24 02:14 Compute
Compute: ELF 64-bit LSB pie executable, x86-64, version 1 (SYSV), dynamically linked, interpreter /lib64/ld-linux-x86-64.so.2, not stripped
```

## [OK] 步骤 5：运行可执行程序

**命令**

```bash
cd /root/wht && ./Compute
```

**含义**：运行可执行程序 Compute，输出计算结果。

**结果**：程序输出 3 + 4 = 7，说明动态库调用成功。

**真实输出**

```
3 + 4 = 7
```

## [OK] 步骤 6：ldd 验证动态库链接

**命令**

```bash
cd /root/wht && ldd Compute | grep add
```

**含义**：用 ldd 命令查看 Compute 程序依赖的动态库，并筛选出与 add 相关的行，确认它链接到了 libadd.so。

**结果**：输出显示 libadd.so 指向 /root/wht+OtherLibs/libadd.so，说明动态库链接正确。

**真实输出**

```
libadd.so => /root/wht+OtherLibs/libadd.so (0x00007ffff7d5c000)
```

## [OK] 步骤 7：make 一键构建

**命令**

```bash
cd /root/wht && make
```

**含义**：执行 make 命令，根据 Makefile 自动编译源代码，生成目标文件和可执行文件。

**结果**：依次编译了 del_str.c、print_str.c、mystr.c 生成对应的 .o 文件，最后链接生成可执行文件 Str。

**真实输出**

```
gcc -c -o del_str.o del_str.c
gcc -c -o print_str.o print_str.c
gcc -c -o mystr.o mystr.c
gcc -o Str del_str.o print_str.o mystr.o
```

## [OK] 步骤 8：运行 make 产物

**命令**

```bash
cd /root/wht && ./Str
```

**含义**：运行 make 生成的可执行文件 Str，查看程序输出。

**结果**：程序输出一行字符串：Hllo Linux, wlcom to C Programming!

**真实输出**

```
Hllo Linux, wlcom to C Programming!
```

## [OK] 步骤 9：make clean 清理中间产物

**命令**

```bash
cd /root/wht && make clean
```

**含义**：执行 make clean 命令，删除编译产生的中间目标文件和可执行文件，清理构建目录。

**结果**：删除了 del_str.o、print_str.o、mystr.o 和 Str 文件。

**真实输出**

```
rm -f del_str.o print_str.o mystr.o Str
```
