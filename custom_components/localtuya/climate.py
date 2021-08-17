"""Platform to locally control Tuya-based climate devices."""
import asyncio
import logging
import json
from functools import partial
import json

import voluptuous as vol
from homeassistant.components.climate import (
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_TEMP,
    DOMAIN,
    ClimateEntity,
)
from homeassistant.components.climate.const import (
    HVAC_MODE_AUTO,
    HVAC_MODE_HEAT,
    HVAC_MODE_OFF,
    HVAC_MODE_COOL,
    HVAC_MODE_HEAT_COOL,
    HVAC_MODE_DRY,
    HVAC_MODE_FAN_ONLY,
    SUPPORT_FAN_MODE,
    SUPPORT_PRESET_MODE,
    SUPPORT_TARGET_TEMPERATURE,
    SUPPORT_TARGET_TEMPERATURE_RANGE,
    CURRENT_HVAC_OFF,
    CURRENT_HVAC_HEAT,
    CURRENT_HVAC_COOL,
    PRESET_NONE,
    PRESET_ECO,
    PRESET_AWAY,
    PRESET_BOOST,
    PRESET_COMFORT,
    PRESET_HOME,
    PRESET_SLEEP,
    PRESET_ACTIVITY,
    FAN_LOW,
    FAN_MEDIUM,
    FAN_HIGH,
)
from homeassistant.const import (
    ATTR_TEMPERATURE,
    CONF_TEMPERATURE_UNIT,
    PRECISION_HALVES,
    PRECISION_TENTHS,
    PRECISION_WHOLE,
    TEMP_CELSIUS,
    TEMP_FAHRENHEIT,
)

from .common import LocalTuyaEntity, async_setup_entry
from .const import (
    CONF_CURRENT_TEMPERATURE_DP,
    CONF_FAN_MODE_DP,
    CONF_MAX_TEMP_DP,
    CONF_MIN_TEMP_DP,
    CONF_PRECISION,
    CONF_TARGET_PRECISION,
    CONF_TARGET_TEMPERATURE_DP,
    CONF_TEMPERATURE_STEP,
    CONF_HVAC_MODE_DP,
    CONF_HVAC_MODE_SET,
    CONF_EURISTIC_ACTION,
    CONF_HVAC_ACTION_DP,
    CONF_HVAC_ACTION_SET,
    CONF_ECO_DP,
    CONF_ECO_VALUE,
    CONF_PRESET_DP,
    CONF_PRESET_SET,
    CONF_FAN_MODE_SET,
)

from . import pytuya

_LOGGER = logging.getLogger(__name__)

HVAC_MODE_SETS = {
    "manual/auto": {
        HVAC_MODE_HEAT: "manual",
        HVAC_MODE_AUTO: "auto",
    },
    "Manual/Auto": {
        HVAC_MODE_HEAT: "Manual",
        HVAC_MODE_AUTO: "Auto",
    },
    "True/False": {
        HVAC_MODE_HEAT: True,
    },
    "Breville": {
        HVAC_MODE_COOL: "heat_low",
        HVAC_MODE_HEAT: ["heat_high", "heat_0"],
    }
}
HVAC_ACTION_SETS = {
    "Breville": {
        CURRENT_HVAC_HEAT: ["heat_high", "heat_0"],
        CURRENT_HVAC_COOL: "Cooling",
    },
    "True/False": {
        CURRENT_HVAC_HEAT: True,
        CURRENT_HVAC_OFF: False,
    },
    "open/close": {
        CURRENT_HVAC_HEAT: "open",
        CURRENT_HVAC_OFF: "close",
    },
    "heating/no_heating": {
        CURRENT_HVAC_HEAT: "heating",
        CURRENT_HVAC_OFF: "no_heating",
    },
}
FAN_SETS = {
    "Breville": {
        FAN_HIGH: "High",
        FAN_MEDIUM: "Medium",
        FAN_LOW: "Low"
    }
}
PRESET_SETS = {
    "Manual/Holiday/Program": {
        PRESET_NONE: "Manual",
        PRESET_AWAY: "Holiday",
        PRESET_HOME: "Program",
    },
}

B_FAN_MODES = {
    HVAC_MODE_HEAT: {
        FAN_LOW: "Heat_High",
        FAN_MEDIUM: "Heat_High",
        FAN_HIGH: "Heat_0",
    },
    HVAC_MODE_COOL: {
        FAN_LOW: "NatureWind_Low",
        FAN_MEDIUM: "NatureWind_High",
        FAN_HIGH: "CoolWind_0",
    }
}

TEMPERATURE_CELSIUS = "celsius"
TEMPERATURE_FAHRENHEIT = "fahrenheit"
DEFAULT_TEMPERATURE_UNIT = TEMPERATURE_CELSIUS
DEFAULT_PRECISION = PRECISION_TENTHS
DEFAULT_TEMPERATURE_STEP = PRECISION_HALVES
MODE_WAIT = 0.1

def flow_schema(dps):
    """Return schema used in config flow."""
    return {
        vol.Optional(CONF_TARGET_TEMPERATURE_DP): vol.In(dps),
        vol.Optional(CONF_CURRENT_TEMPERATURE_DP): vol.In(dps),
        vol.Optional(CONF_TEMPERATURE_STEP): vol.In(
            [PRECISION_WHOLE, PRECISION_HALVES, PRECISION_TENTHS]
        ),
        vol.Optional(CONF_MAX_TEMP_DP): vol.In(dps),
        vol.Optional(CONF_MIN_TEMP_DP): vol.In(dps),
        vol.Optional(CONF_PRECISION): vol.In(
            [PRECISION_WHOLE, PRECISION_HALVES, PRECISION_TENTHS]
        ),
        vol.Optional(CONF_HVAC_MODE_DP): vol.In(dps),
        vol.Optional(CONF_HVAC_MODE_SET): vol.In(
            list(HVAC_MODE_SETS.keys())
        ),
        vol.Optional(CONF_HVAC_ACTION_DP): vol.In(dps),
        vol.Optional(CONF_HVAC_ACTION_SET): vol.In(
            list(HVAC_ACTION_SETS.keys())
        ),
        vol.Optional(CONF_ECO_DP): vol.In(dps),
        vol.Optional(CONF_ECO_VALUE): str,
        vol.Optional(CONF_PRESET_DP): vol.In(dps),
        vol.Optional(CONF_PRESET_SET): vol.In(
            list(PRESET_SETS.keys())
        ),
        vol.Optional(CONF_TEMPERATURE_UNIT): vol.In(
            [TEMPERATURE_CELSIUS, TEMPERATURE_FAHRENHEIT]
        ),
        vol.Optional(CONF_TARGET_PRECISION): vol.In(
            [PRECISION_WHOLE, PRECISION_HALVES, PRECISION_TENTHS]
        ),
        vol.Optional(CONF_EURISTIC_ACTION, default=False): bool,
        vol.Optional(CONF_FAN_MODE_DP): vol.In(dps),
        vol.Optional(CONF_FAN_MODE_SET): vol.In(list(FAN_SETS.keys()))
    }


class LocaltuyaClimate(LocalTuyaEntity, ClimateEntity):
    """Tuya climate device."""

    def __init__(
        self,
        device,
        config_entry,
        switchid,
        **kwargs,
    ):
        """Initialize a new LocaltuyaClimate."""
        super().__init__(device, config_entry, switchid, _LOGGER, **kwargs)
        self._state = None
        self._target_temperature = None
        self._current_temperature = None
        self._hvac_mode = None
        self._preset_mode = None
        self._hvac_action = None
        self._fan_mode = None
        self._precision = self._config.get(CONF_PRECISION, DEFAULT_PRECISION)
        self._target_precision = self._config.get(CONF_TARGET_PRECISION, self._precision)
        self._conf_fan_mode_dp = self._config.get(CONF_FAN_MODE_DP)
        self._conf_fan_mode_set = FAN_SETS.get(self._config.get(CONF_FAN_MODE_SET), {})
        self._conf_hvac_mode_dp = self._config.get(CONF_HVAC_MODE_DP)
        self._conf_hvac_mode_set = HVAC_MODE_SETS.get(self._config.get(CONF_HVAC_MODE_SET), {})
        self._conf_preset_dp = self._config.get(CONF_PRESET_DP)
        self._conf_preset_set = PRESET_SETS.get(self._config.get(CONF_PRESET_SET), {})
        self._conf_hvac_action_dp = self._config.get(CONF_HVAC_ACTION_DP)
        self._conf_hvac_action_set = HVAC_ACTION_SETS.get(self._config.get(CONF_HVAC_ACTION_SET), {})
        self._conf_eco_dp = self._config.get(CONF_ECO_DP)
        self._conf_eco_value = self._config.get(CONF_ECO_VALUE, "ECO")
        self._has_presets = self.has_config(CONF_ECO_DP) or self.has_config(CONF_PRESET_DP)
        print("Initialized climate [{}]".format(self.name))

    @property
    def supported_features(self):
        """Flag supported features."""
        supported_features = 0
        if self.has_config(CONF_TARGET_TEMPERATURE_DP):
            supported_features = supported_features | SUPPORT_TARGET_TEMPERATURE
        if self.has_config(CONF_MAX_TEMP_DP):
            supported_features = supported_features | SUPPORT_TARGET_TEMPERATURE_RANGE
        if self.has_config(CONF_FAN_MODE_DP):
            supported_features = supported_features | SUPPORT_FAN_MODE
        if self.has_config(CONF_PRESET_DP) or self.has_config(CONF_ECO_DP):
            supported_features = supported_features | SUPPORT_PRESET_MODE
        return supported_features

    @property
    def precision(self):
        """Return the precision of the system."""
        return self._precision

    @property
    def target_recision(self):
        """Return the precision of the target."""
        return self._target_precision

    @property
    def temperature_unit(self):
        """Return the unit of measurement used by the platform."""
        if (
            self._config.get(CONF_TEMPERATURE_UNIT, DEFAULT_TEMPERATURE_UNIT)
            == TEMPERATURE_FAHRENHEIT
        ):
            return TEMP_FAHRENHEIT
        return TEMP_CELSIUS

    @property
    def hvac_mode(self):
        """Return current operation ie. heat, cool, idle."""
        return self._hvac_mode

    @property
    def hvac_modes(self):
        """Return the list of available operation modes."""
        if not self.has_config(CONF_HVAC_MODE_DP):
            return None
        return list(self._conf_hvac_mode_set) + [HVAC_MODE_OFF]

    @property
    def hvac_action(self):
        """Return the current running hvac operation if supported.
        Need to be one of CURRENT_HVAC_*.
        """
        if self._config[CONF_EURISTIC_ACTION]:
            if self._hvac_mode == HVAC_MODE_HEAT:
                if self._current_temperature < (self._target_temperature - self._precision):
                    self._hvac_action = CURRENT_HVAC_HEAT
                if self._current_temperature == (self._target_temperature - self._precision):
                    if self._hvac_action == CURRENT_HVAC_HEAT:
                        self._hvac_action = CURRENT_HVAC_HEAT
                    if self._hvac_action == CURRENT_HVAC_OFF:
                        self._hvac_action = CURRENT_HVAC_OFF
                if (self._current_temperature + self._precision) > self._target_temperature:
                    self._hvac_action = CURRENT_HVAC_OFF
            return self._hvac_action
        return self._hvac_action

    @property
    def preset_mode(self):
        """Return current preset"""
        return self._preset_mode

    @property
    def preset_modes(self):
        """Return the list of available presets modes."""
        if not self._has_presets:
            return None
        presets = list(self._conf_preset_set)
        if self._conf_eco_dp:
            presets.append(PRESET_ECO)
        return presets

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self._current_temperature

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self._target_temperature

    @property
    def target_temperature_step(self):
        """Return the supported step of target temperature."""
        return self._config.get(CONF_TEMPERATURE_STEP, DEFAULT_TEMPERATURE_STEP)

    @property
    def fan_mode(self):
        """Return the fan setting."""
        if self._conf_fan_mode_set:
            return self._fan_mode
        return NotImplementedError()

    @property
    def fan_modes(self):
        """Return the list of available fan modes."""
        if self._conf_fan_mode_set:
            return self._conf_fan_mode_set
        return NotImplementedError()

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        if ATTR_TEMPERATURE in kwargs and self.has_config(CONF_TARGET_TEMPERATURE_DP):
            temperature = round(kwargs[ATTR_TEMPERATURE] / self._target_precision)
            await self._device.set_dp(temperature, self._config[CONF_TARGET_TEMPERATURE_DP])

    async def async_set_fan_mode(self, fan_mode):
        """Set new target fan mode."""
        if self._config.get(CONF_FAN_MODE_SET) == "Breville":
            if self._hvac_mode == HVAC_MODE_COOL:
                await self._device.set_dp(B_FAN_MODES[self._hvac_mode][fan_mode], self._conf_fan_mode_dp)
            else:
                await self._device.set_dp(B_FAN_MODES[self._hvac_mode][fan_mode], self._conf_hvac_mode_dp)
            return

        return NotImplementedError()

    async def async_set_hvac_mode(self, hvac_mode):
        """Set new target operation mode."""
        if hvac_mode == HVAC_MODE_OFF:
            await self._device.set_dp(False, self._dp_id)
            return
        if not self._state and self._conf_hvac_mode_dp != self._dp_id:
            await self._device.set_dp(True, self._dp_id)
            await asyncio.sleep(MODE_WAIT)

        if self._config.get(CONF_HVAC_ACTION_SET) == "Breville":
            if hvac_mode == HVAC_MODE_HEAT:
                await self._device.set_dp("heat_high", self._conf_hvac_mode_dp)
            elif hvac_mode == HVAC_MODE_COOL:
                await self._device.set_dp("NatureWind_High", self._conf_fan_mode_dp)
        else:
            await self._device.set_dp(self._conf_hvac_mode_set[hvac_mode], self._conf_hvac_mode_dp)

    async def async_set_preset_mode(self, preset_mode):
        """Set new target preset mode."""
        if preset_mode == PRESET_ECO:
            await self._device.set_dp(self._conf_eco_value, self._conf_eco_dp)
            return
        await self._device.set_dp(self._conf_preset_set[preset_mode], self._conf_preset_dp)

    @property
    def min_temp(self):
        """Return the minimum temperature."""
        if self.has_config(CONF_MIN_TEMP_DP):
            return self.dps_conf(CONF_MIN_TEMP_DP)
        return DEFAULT_MIN_TEMP

    @property
    def max_temp(self):
        """Return the maximum temperature."""
        if self.has_config(CONF_MAX_TEMP_DP):
            return self.dps_conf(CONF_MAX_TEMP_DP)
        return DEFAULT_MAX_TEMP

    def status_updated(self):
        """Device status was updated."""
        self._state = self.dps(self._dp_id)

        if self.has_config(CONF_TARGET_TEMPERATURE_DP):
            self._target_temperature = (
                self.dps_conf(CONF_TARGET_TEMPERATURE_DP) * self._target_precision
            )

        if self.has_config(CONF_CURRENT_TEMPERATURE_DP):
            self._current_temperature = (
                self.dps_conf(CONF_CURRENT_TEMPERATURE_DP) * self._precision
            )

        #_LOGGER.debug("the test is %s", test)he preset status"""
        if self._has_presets:
            if self.has_config(CONF_ECO_DP) and self.dps_conf(CONF_ECO_DP) == self._conf_eco_value:
                self._preset_mode = PRESET_ECO
            else:
                for preset,value in self._conf_preset_set.items(): # todo remove
                    if self.dps_conf(CONF_PRESET_DP) == value:
                        self._preset_mode = preset
                        break
                else:
                    self._preset_mode = PRESET_NONE

        """Update the HVAC status"""
        if self.has_config(CONF_HVAC_MODE_DP):
            if not self._state:
                self._hvac_mode = HVAC_MODE_OFF
            else:
                for mode,value in self._conf_hvac_mode_set.items():
                    if self.dps_conf(CONF_HVAC_MODE_DP) == value or self.dps_conf(CONF_HVAC_MODE_DP) in value:
                        self._hvac_mode = mode
                        break
                else:
                    # in case hvac mode and preset share the same dp
                    self._hvac_mode = HVAC_MODE_AUTO

        """Update the current action"""
        if self.has_config(CONF_HVAC_ACTION_DP):
            for action,value in self._conf_hvac_action_set.items():
                if self.dps_conf(CONF_HVAC_ACTION_DP) == value or self.dps_conf(CONF_HVAC_ACTION_DP) in value:
                    self._hvac_action = action

        """Update the fan mode"""
        if self._config.get(CONF_FAN_MODE_SET) == "Breville":
            for k,v in B_FAN_MODES[self._hvac_mode].items():
                if self._hvac_mode == HVAC_MODE_COOL:
                    if v == self.dps_conf(CONF_FAN_MODE_DP):
                        self._fan_mode = k
                else:
                    if v == self.dps_conf(CONF_HVAC_MODE_DP):
                        self._fan_mode = k

async_setup_entry = partial(async_setup_entry, DOMAIN, LocaltuyaClimate, flow_schema)
