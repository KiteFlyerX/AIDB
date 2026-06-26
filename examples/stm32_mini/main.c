/*
 * main.c — STM32 主程序(M1 测试工程)
 * SPDX-License-Identifier: GPL-3.0-or-later
 * Copyright (c) KiteFlyerX
 */
#include <stdint.h>
#include "uart.h"

/* 板载 LED 引脚宏(测试 numeric 宏) */
#define LED_PIN     13
#define BLINK_DELAY 1000

/* 错误处理(测试无参函数) */
void Error_Handler(void)
{
    while (1) {
        /* 死循环 */
    }
}

/* LED 翻转(测试 static 函数 + 宏引用 + 内部调用) */
static void led_toggle(void)
{
    static uint8_t state = 0;
    state = (state == 0) ? 1 : 0;
    (void)LED_PIN;
}

/* 主函数(测试:初始化串口、调用 uart_send 发送字符串、循环) */
int main(void)
{
    uart_cfg_t cfg = { UART2, UART_DEFAULT_BAUD, 2 };
    uint8_t msg[] = { 'H', 'i', 0 };
    int sent;

    uart_init(&cfg);
    sent = uart_send(msg, 2);
    if (sent < 0) {
        Error_Handler();
    }

    while (1) {
        led_toggle();
        uart_wait_ready(UART2);
    }
    return 0;
}
