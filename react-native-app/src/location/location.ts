import * as Location from 'expo-location'

/**
 * Location has two explicit paths in KARMA — neither invents coordinates.
 *
 * This module owns the device-fix path. It asks the operating system for one
 * one-time, foreground, high-accuracy fix and nothing more: no background
 * location permission is ever requested, matching the Android/iOS strings
 * the backend's consent contract describes.
 *
 * The *consent* conversation — KARMA's disclosure before the OS prompt — is
 * shown by the caller (it is UI copy), then this function is called.
 */

export type DeviceFix = {
  lat: number
  lng: number
  accuracy_m: number | null
}

export class LocationUnavailableError extends Error {}

export async function getConsentedDeviceFix(): Promise<DeviceFix> {
  const status = await Location.getForegroundPermissionsAsync()
  if (!status.granted) {
    const requested = await Location.requestForegroundPermissionsAsync()
    if (!requested.granted) {
      throw new LocationUnavailableError('Location permission was not granted.')
    }
  }

  let position: Location.LocationObject
  try {
    // One one-time foreground fix at high accuracy. No `maximumAge`: we want
    // the freshest fix, and the OS prompt is the disclosure the user agreed to.
    position = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High })
  } catch {
    throw new LocationUnavailableError('Location was unavailable or timed out.')
  }

  return {
    lat: position.coords.latitude,
    lng: position.coords.longitude,
    accuracy_m: position.coords.accuracy ?? null,
  }
}

/** A one-line description of a fix, for the "editing does not move it" notes. */
export function describeFix(fix: DeviceFix): string {
  const accuracy =
    fix.accuracy_m != null && fix.accuracy_m > 0 ? ` · ±${Math.round(fix.accuracy_m)} m` : ''
  return `One-time device fix selected${accuracy}. Editing the label does not move it.`
}
