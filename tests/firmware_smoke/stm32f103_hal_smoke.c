/*
 * Original compile-only smoke harness for the APIs used throughout the V1
 * lessons. It is deliberately not a board project and performs no flashing.
 */
#include "stm32f1xx_hal.h"

extern ADC_HandleTypeDef hadc1;
extern CAN_HandleTypeDef hcan;
extern I2C_HandleTypeDef hi2c1;
extern RTC_HandleTypeDef hrtc;
extern SPI_HandleTypeDef hspi1;
extern TIM_HandleTypeDef htim2;
extern UART_HandleTypeDef huart1;

static uint16_t samples[16];
static volatile uint32_t last_capture;
static volatile uint8_t button_event;

void mentor_hal_api_smoke(void)
{
    uint8_t byte = 0x55U;
    RTC_TimeTypeDef time = {0};

    HAL_GPIO_WritePin(GPIOA, GPIO_PIN_0, GPIO_PIN_SET);
    HAL_GPIO_TogglePin(GPIOA, GPIO_PIN_0);
    (void)HAL_TIM_PWM_Start(&htim2, TIM_CHANNEL_1);
    __HAL_TIM_SET_COMPARE(&htim2, TIM_CHANNEL_1, 500U);
    (void)HAL_UART_Transmit(&huart1, &byte, 1U, 100U);
    (void)HAL_ADC_Start(&hadc1);
    (void)HAL_ADC_PollForConversion(&hadc1, 10U);
    (void)HAL_ADC_GetValue(&hadc1);
    (void)HAL_ADC_Start_DMA(&hadc1, (uint32_t *)samples, 16U);
    (void)HAL_I2C_Mem_Read(&hi2c1, 0x44U << 1, 0U, I2C_MEMADD_SIZE_8BIT, &byte, 1U, 100U);
    (void)HAL_SPI_Transmit(&hspi1, &byte, 1U, 100U);
    (void)HAL_RTC_GetTime(&hrtc, &time, RTC_FORMAT_BIN);
    (void)HAL_TIM_IC_Start_IT(&htim2, TIM_CHANNEL_1);
    (void)HAL_CAN_Start(&hcan);
}

void HAL_GPIO_EXTI_Callback(uint16_t pin)
{
    if (pin == GPIO_PIN_0) {
        button_event = 1U;
    }
}

void HAL_TIM_IC_CaptureCallback(TIM_HandleTypeDef *timer)
{
    if (timer->Channel == HAL_TIM_ACTIVE_CHANNEL_1) {
        last_capture = HAL_TIM_ReadCapturedValue(timer, TIM_CHANNEL_1);
    }
}

