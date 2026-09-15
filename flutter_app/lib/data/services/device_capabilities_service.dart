import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import 'package:image_picker/image_picker.dart';

class PendingImage {
  const PendingImage({required this.name, required this.bytes});

  final String name;
  final Uint8List bytes;
}

class DeviceCapabilitiesService {
  DeviceCapabilitiesService({ImagePicker? imagePicker})
      : _imagePicker = imagePicker ?? ImagePicker();

  final ImagePicker _imagePicker;

  Future<PendingImage?> pickImage(BuildContext context) async {
    final ImageSource? source = await showModalBottomSheet<ImageSource>(
      context: context,
      showDragHandle: true,
      builder: (BuildContext context) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 18),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              Text('Add a photo', style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 10),
              ListTile(
                leading: const Icon(Icons.camera_alt_outlined),
                title: const Text('Take a photo'),
                subtitle: const Text('KARMA requests camera access only after you choose this.'),
                onTap: () => Navigator.pop(context, ImageSource.camera),
              ),
              ListTile(
                leading: const Icon(Icons.photo_library_outlined),
                title: const Text('Choose from library'),
                subtitle: const Text('You choose the single image KARMA can read.'),
                onTap: () => Navigator.pop(context, ImageSource.gallery),
              ),
            ],
          ),
        ),
      ),
    );
    if (source == null) return null;
    final XFile? selected = await _imagePicker.pickImage(
      source: source,
      maxWidth: 2048,
      maxHeight: 2048,
      imageQuality: 86,
      requestFullMetadata: false,
    );
    if (selected == null) return null;
    final Uint8List bytes = await selected.readAsBytes();
    if (bytes.length > 5 * 1024 * 1024) {
      throw const FormatException('Choose an image smaller than 5 MB.');
    }
    return PendingImage(name: selected.name, bytes: bytes);
  }

  Future<Position> currentPosition() async {
    if (!await Geolocator.isLocationServiceEnabled()) {
      throw const FormatException(
        'Location services are off. Turn them on, then try again.',
      );
    }
    LocationPermission permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
    }
    if (permission == LocationPermission.denied) {
      throw const FormatException('Location permission was not granted.');
    }
    if (permission == LocationPermission.deniedForever) {
      throw const FormatException(
        'Location permission is blocked. Enable it in system settings to continue.',
      );
    }
    return Geolocator.getCurrentPosition(
      locationSettings: const LocationSettings(
        accuracy: LocationAccuracy.high,
        timeLimit: Duration(seconds: 15),
      ),
    );
  }
}

Future<bool> confirmLocationConsent(
  BuildContext context, {
  required String title,
  required String action,
  required bool includesGeocoder,
}) async =>
    await showDialog<bool>(
      context: context,
      builder: (BuildContext context) => AlertDialog(
        icon: const Icon(Icons.my_location_rounded),
        title: Text(title),
        content: Text(
          includesGeocoder
              ? 'KARMA will send this location to its API for nearby matching and to the named geocoding provider for an address label. It is saved on the gig and shared with the assigned worker. Location is never requested in the background.'
              : 'KARMA will request a precise location now and send it to its API so nearby customers can find you while you are online. It is not requested in the background.',
        ),
        actions: <Widget>[
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Not now'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: Text(action),
          ),
        ],
      ),
    ) ??
    false;

Future<bool> confirmAddressLookup(BuildContext context) async =>
    await showDialog<bool>(
      context: context,
      builder: (BuildContext context) => AlertDialog(
        icon: const Icon(Icons.manage_search_rounded),
        title: const Text('Search this address?'),
        content: const Text(
          'The address you typed will be sent to KARMA’s configured geocoding provider. KARMA stores only the result you choose with the gig; searching does not silently move a map pin.',
        ),
        actions: <Widget>[
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('I agree · search'),
          ),
        ],
      ),
    ) ??
    false;
