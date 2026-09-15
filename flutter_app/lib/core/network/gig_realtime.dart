import 'dart:async';
import 'dart:convert';

import 'package:web_socket_channel/status.dart' as status;
import 'package:web_socket_channel/web_socket_channel.dart';

import '../../data/repositories/karma_repository.dart';

class GigEvent {
  const GigEvent({
    required this.type,
    required this.gigId,
    required this.data,
  });

  factory GigEvent.fromJson(Map<String, Object?> map) {
    final Object? rawData = map['data'];
    final Map<String, Object?> data = rawData is Map
        ? rawData.map<String, Object?>((Object? key, Object? value) {
            return MapEntry<String, Object?>(key.toString(), value);
          })
        : <String, Object?>{};
    return GigEvent(
      type: map['type'] as String? ?? '',
      gigId: (map['gig_id'] as num?)?.toInt() ?? 0,
      data: data,
    );
  }

  final String type;
  final int gigId;
  final Map<String, Object?> data;
}

enum LiveConnectionState { connecting, live, paused }

/// Reconnecting, ticket-based gig updates. Each reconnect obtains a fresh
/// single-use ticket; the JWT never enters the socket URL.
class GigRealtimeConnection {
  GigRealtimeConnection({
    required this.repository,
    required this.gigId,
    required this.onEvent,
    required this.onState,
  });

  final KarmaRepository repository;
  final int gigId;
  final ValueChanged<GigEvent> onEvent;
  final ValueChanged<LiveConnectionState> onState;

  WebSocketChannel? _channel;
  StreamSubscription<Object?>? _subscription;
  Timer? _reconnectTimer;
  int _attempts = 0;
  bool _closed = false;

  Future<void> open() async {
    if (_closed) return;
    onState(LiveConnectionState.connecting);
    try {
      final String ticket = await repository.realtimeTicket();
      if (_closed) return;
      final Uri uri = repository.api.websocketUri(
        '/realtime/gigs/$gigId',
        <String, String>{'ticket': ticket},
      );
      final WebSocketChannel channel = WebSocketChannel.connect(uri);
      await channel.ready.timeout(const Duration(seconds: 8));
      if (_closed) {
        await channel.sink.close(status.goingAway);
        return;
      }
      _channel = channel;
      _attempts = 0;
      onState(LiveConnectionState.live);
      _subscription = channel.stream.listen(
        _handleMessage,
        onError: (Object error, StackTrace stackTrace) => _reconnect(),
        onDone: _reconnect,
        cancelOnError: true,
      );
    } on Object {
      _reconnect();
    }
  }

  void _handleMessage(Object? raw) {
    if (raw is! String) return;
    try {
      final Object? decoded = jsonDecode(raw);
      if (decoded is! Map) return;
      final Map<String, Object?> map = decoded.map<String, Object?>(
        (Object? key, Object? value) => MapEntry<String, Object?>(key.toString(), value),
      );
      final String type = map['type'] as String? ?? '';
      if (type == 'ping') {
        _channel?.sink.add('ping');
        return;
      }
      if (type != 'pong') onEvent(GigEvent.fromJson(map));
    } on FormatException {
      // A malformed frame is ignored; last trusted state remains visible.
    }
  }

  void _reconnect() {
    if (_closed || _reconnectTimer?.isActive == true) return;
    _subscription?.cancel();
    _subscription = null;
    _channel = null;
    onState(LiveConnectionState.paused);
    if (_attempts >= 5) return;
    _attempts += 1;
    final int seconds = (_attempts * 2).clamp(2, 15);
    _reconnectTimer = Timer(Duration(seconds: seconds), open);
  }

  Future<void> close() async {
    _closed = true;
    _reconnectTimer?.cancel();
    await _subscription?.cancel();
    await _channel?.sink.close(status.goingAway);
    onState(LiveConnectionState.paused);
  }
}

typedef ValueChanged<T> = void Function(T value);
