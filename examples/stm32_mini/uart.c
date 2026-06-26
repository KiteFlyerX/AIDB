/*
 * uart.c — STM32 串口驱动实现(M1 测试工程)
 * SPDX-License-Identifier: GPL-3.0-or-later
 * Copyright (c) KiteFlyerX
 */
#include "uart.h"

/* 静态发送缓冲区(测试全局变量定义) */
static uint8_t tx_buf[UART_TX_BUF_SIZE];
static uint32_t tx_len = 0;

/* 内部:等待发送寄存器就绪(测试 static 函数 + 调用) */
static void uart_wait_ready(uart_id_t id)
{
    /* 简化的忙等待,实际工程会读 USART_SR 的 TXE 位 */
    volatile uint32_t *sr = (volatile uint32_t *)(0x40011000UL + (uint32_t)id * 0x400UL);
    while ((*sr & 0x80UL) == 0) {
        /* 等待 TXE 置位 */
    }
}

/* 初始化串口(测试带指针参数的函数定义 + 内部调用) */
void uart_init(const uart_cfg_t *cfg)
{
    if (cfg == 0) {
        return;
    }
    /* 实际工程会配置 GPIO 复用 + 波特率寄存器 */
    tx_len = 0;
    (void)cfg->baud;   /* 此处仅示意 */
    uart_wait_ready(cfg->id);
}

/* 发送数据(测试循环 + 数组访问 + 返回值) */
int uart_send(const uint8_t *data, uint32_t len)
{
    uint32_t i;
    if (data == 0 || len == 0) {
        return 0;
    }
    for (i = 0; i < len && i < UART_TX_BUF_SIZE; i++) {
        tx_buf[i] = data[i];
    }
    tx_len = i;
    uart_wait_ready(UART2);
    return (int)i;
}

/* 接收数据(测试简单的 memcpy 风格实现) */
int uart_receive(uint8_t *buf, uint32_t maxlen)
{
    uint32_t i;
    uint32_t n = (tx_len < maxlen) ? tx_len : maxlen;
    if (buf == 0) {
        return 0;
    }
    for (i = 0; i < n; i++) {
        buf[i] = tx_buf[i];
    }
    return (int)n;
}
