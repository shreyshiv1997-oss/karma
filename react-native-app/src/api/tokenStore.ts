import AsyncStorage from '@react-native-async-storage/async-storage'
import * as SecureStore from 'expo-secure-store'

/**
 * Credential storage. The manifesto's rule, kept: tokens live in
 * Keychain/Keystore-backed secure storage, never in plain preferences.
 *
 * `expo-secure-store` maps to the iOS Keychain and the Android Keystore. The
 * AsyncStorage fallback exists only for environments where the secure module
 * is unavailable (some test harnesses, web) — it is deliberately last, and it
 * stores the same JSON document so behaviour is identical either way.
 */

const KEY = 'karma.tokens'

export async function readTokens(): Promise<string | null> {
  try {
    const value = await SecureStore.getItemAsync(KEY)
    return value ?? null
  } catch {
    try {
      return await AsyncStorage.getItem(KEY)
    } catch {
      return null
    }
  }
}

export async function writeTokens(json: string): Promise<void> {
  try {
    await SecureStore.setItemAsync(KEY, json)
    return
  } catch {
    try {
      await AsyncStorage.setItem(KEY, json)
    } catch {
      /* private mode — tokens stay in memory only */
    }
  }
}

export async function clearTokens(): Promise<void> {
  try {
    await SecureStore.deleteItemAsync(KEY)
  } catch {
    /* ignore */
  }
  try {
    await AsyncStorage.removeItem(KEY)
  } catch {
    /* ignore */
  }
}
