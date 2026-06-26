/*
 * uart.h — STM32 串口驱动头文件(M1 测试工程)
 * SPDX-License-Identifier: GPL-3.0-or-later
 * Copyright (c) KiteFlyerX
 */
#ifndef UART_H
#define UART_H

#include <stdint.h>

/* 串口号枚举(测试 enum 定义提取) */
typedef enum {
    UART1 = 0,
    UART2 = 1,
    UART3 = 2
} uart_id_t;

/* 串口配置结构体(测试 typedef struct 提取 + 字段) */
typedef struct {
    uart_id_t   id;       /* 串口号 */
    uint32_t    baud;     /* 波特率 */
    uint8_t     port;     /* GPIO 端口号 */
} uart_cfg_t;

/* 宏定义(测试 preproc_def 提取) */
#define UART_DEFAULT_BAUD   115200
#define UART_TX_BUF_SIZE    128

/* 函数原型(测试 declaration 中的函数原型作为 def) */
void uart_init(const uart_cfg_t *cfg);
int  uart_send(const uint8_t *data, uint32_t len);
int  uart_receive(uint8_t *buf, uint32_t maxlen);

#endif /* UART_H */
