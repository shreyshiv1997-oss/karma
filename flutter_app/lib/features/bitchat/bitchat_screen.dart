import 'dart:ui' show FontFeature;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../../core/bitchat/bitchat_mesh.dart';
import '../../core/network/gig_realtime.dart';
import '../../core/theme/app_theme.dart';
import '../../data/models/models.dart';
import '../../data/repositories/karma_repository.dart';
import '../../shared/widgets/primitives.dart';
import '../auth/session_controller.dart';
import 'bitchat_controller.dart';

class BitchatScreen extends StatefulWidget {
  const BitchatScreen({required this.gig, super.key});

  final Gig gig;

  @override
  State<BitchatScreen> createState() => _BitchatScreenState();
}

class _BitchatScreenState extends State<BitchatScreen> {
  final TextEditingController _composer = TextEditingController();
  final ScrollController _scroll = ScrollController();
  late final BitchatController _controller;
  int _lastMessageCount = 0;
  bool _panicking = false;

  @override
  void initState() {
    super.initState();
    final User user = context.read<SessionController>().user!;
    _controller = BitchatController(
      repository: context.read<KarmaRepository>(),
      user: user,
      gig: widget.gig,
    )
      ..addListener(_followMessages)
      ..initialize();
  }

  @override
  void dispose() {
    _controller
      ..removeListener(_followMessages)
      ..dispose();
    _composer.dispose();
    _scroll.dispose();
    super.dispose();
  }

  void _followMessages() {
    if (_lastMessageCount == _controller.messages.length) return;
    _lastMessageCount = _controller.messages.length;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !_scroll.hasClients) return;
      _scroll.animateTo(
        _scroll.position.maxScrollExtent,
        duration: AppTheme.enter,
        curve: AppTheme.curve,
      );
    });
  }

  Future<void> _send() async {
    final String text = _composer.text;
    if (text.trim().isEmpty || _controller.sending) return;
    _composer.clear();
    HapticFeedback.selectionClick();
    await _controller.send(text);
  }

  Future<void> _confirmPanic() async {
    if (_panicking || _controller.wiped) return;
    final bool confirmed = await showDialog<bool>(
          context: context,
          builder: (BuildContext context) => AlertDialog(
            icon: const Icon(Icons.sos_rounded, color: AppColors.rose, size: 34),
            title: const Text('Alert safety and erase Bitchat?'),
            content: const Text(
              'This revokes this device identity, destroys every local Bitchat transcript and key, and cannot be undone.',
            ),
            actions: <Widget>[
              TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: const Text('Keep chat'),
              ),
              FilledButton.icon(
                style: FilledButton.styleFrom(backgroundColor: AppColors.rose),
                onPressed: () => Navigator.pop(context, true),
                icon: const Icon(Icons.delete_forever_outlined),
                label: const Text('Alert & erase'),
              ),
            ],
          ),
        ) ??
        false;
    if (confirmed && mounted) await _panic();
  }

  Future<void> _panic() async {
    if (_panicking || _controller.wiped) return;
    setState(() => _panicking = true);
    HapticFeedback.heavyImpact();
    final bool acknowledged = await _controller.panicAndWipe();
    if (!mounted) return;
    setState(() => _panicking = false);
    final bool erased = _controller.wipeComplete;
    final String message = switch ((acknowledged, erased)) {
      (true, true) =>
        'Safety team alerted. Local messages and device keys were erased.',
      (true, false) =>
        'Safety team alerted, but secure storage could not confirm a complete local erase.',
      (false, true) =>
        'Local keys erased, but the safety server was unreachable. Call local emergency services if you are in danger.',
      (false, false) =>
        'Safety could not be reached and secure storage could not confirm a complete erase. Call local emergency services now.',
    };
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        duration: const Duration(seconds: 7),
        backgroundColor: acknowledged && erased ? AppColors.ink : AppColors.rose,
        content: Text(message),
      ),
    );
  }

  void _showSecurityDetails() {
    showModalBottomSheet<void>(
      context: context,
      useSafeArea: true,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (BuildContext context) => const _SecuritySheet(),
    );
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
        animation: _controller,
        builder: (BuildContext context, _) {
          final BitchatSession? session = _controller.session;
          return Scaffold(
            appBar: AppBar(
              titleSpacing: 4,
              title: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Text(
                    session?.peerAlias ?? 'Ephemeral chat',
                    style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800),
                  ),
                  Text(
                    'Gig #${widget.gig.id} · no transcript on the server',
                    style: const TextStyle(
                      color: AppColors.textFaint,
                      fontSize: 10.5,
                      fontWeight: FontWeight.w500,
                    ),
                  ),
                ],
              ),
              actions: <Widget>[
                IconButton(
                  tooltip: 'How Bitchat protects this conversation',
                  onPressed: _showSecurityDetails,
                  icon: const Icon(Icons.enhanced_encryption_outlined),
                ),
                Semantics(
                  button: true,
                  label: 'Panic now, alert safety, and erase chat keys',
                  child: IconButton.filled(
                    tooltip: 'Panic & erase keys',
                    onPressed: _panicking ? null : _confirmPanic,
                    style: IconButton.styleFrom(
                      backgroundColor: AppColors.rose,
                      foregroundColor: Colors.white,
                    ),
                    icon: _panicking
                        ? const SizedBox.square(
                            dimension: 18,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: Colors.white,
                            ),
                          )
                        : const Icon(Icons.sos_rounded),
                  ),
                ),
                const SizedBox(width: 8),
              ],
            ),
            body: SafeArea(
              top: false,
              child: _controller.loading
                  ? const Center(child: CircularProgressIndicator())
                  : _controller.wiped
                      ? ContentRail(
                          child: EmptyState(
                            icon: _controller.wipeComplete
                                ? Icons.delete_forever_outlined
                                : Icons.warning_amber_rounded,
                            title: _controller.wipeComplete
                                ? 'This device was wiped'
                                : 'Secure erase needs attention',
                            message: _controller.wipeComplete
                                ? 'The key identity and local transcript are gone. Reopen chat to create a fresh identity after you are safe.'
                                : 'KARMA disabled this conversation but could not confirm every secure-storage deletion. Lock or erase this device after contacting emergency services.',
                          ),
                        )
                      : Column(
                          children: <Widget>[
                            Expanded(
                              child: Align(
                                alignment: Alignment.topCenter,
                                child: ConstrainedBox(
                                  constraints: const BoxConstraints(maxWidth: 760),
                                  child: Column(
                                    children: <Widget>[
                                      _ControlDeck(
                                        controller: _controller,
                                        onSecurity: _showSecurityDetails,
                                      ),
                                      if (_controller.error != null)
                                        _ChatError(
                                          error: _controller.error!,
                                          onRetry: _controller.refreshInbox,
                                        ),
                                      Expanded(
                                        child: _MessageList(
                                          messages: _controller.messages,
                                          peerAlias: session?.peerAlias ?? 'Peer',
                                          scrollController: _scroll,
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                              ),
                            ),
                            _Composer(
                              controller: _composer,
                              enabled: _controller.canSend &&
                                  (session?.peerDevices.isNotEmpty ?? false),
                              sending: _controller.sending,
                              peerReady: session?.peerDevices.isNotEmpty ?? false,
                              onSend: _send,
                            ),
                          ],
                        ),
            ),
          );
        },
      );
}

class _ControlDeck extends StatelessWidget {
  const _ControlDeck({
    required this.controller,
    required this.onSecurity,
  });

  final BitchatController controller;
  final VoidCallback onSecurity;

  @override
  Widget build(BuildContext context) {
    final bool meshReady = controller.meshState == BitchatMeshState.ready;
    final bool serverReady = controller.serverState == LiveConnectionState.live;
    return Container(
      margin: const EdgeInsets.fromLTRB(12, 10, 12, 7),
      padding: const EdgeInsets.fromLTRB(13, 12, 13, 11),
      decoration: BoxDecoration(
        color: AppColors.surface,
        border: Border.all(color: AppColors.line),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        children: <Widget>[
          Row(
            children: <Widget>[
              const Icon(Icons.lock_rounded, size: 17, color: AppColors.lime),
              const SizedBox(width: 7),
              const Expanded(
                child: Text(
                  'End-to-end encrypted · keys live on devices',
                  style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700),
                ),
              ),
              InkWell(
                borderRadius: BorderRadius.circular(8),
                onTap: onSecurity,
                child: const Padding(
                  padding: EdgeInsets.symmetric(horizontal: 4, vertical: 3),
                  child: Text(
                    'DETAILS',
                    style: TextStyle(
                      color: AppColors.violetInk,
                      fontSize: 9.5,
                      fontWeight: FontWeight.w800,
                      letterSpacing: 0.5,
                    ),
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          _ModeControls(controller: controller),
          const SizedBox(height: 9),
          Row(
            children: <Widget>[
              _TransportState(
                icon: Icons.cloud_outlined,
                label: serverReady ? 'Relay live' : 'Relay reconnecting',
                active: serverReady,
              ),
              const SizedBox(width: 12),
              _TransportState(
                icon: Icons.bluetooth_searching_rounded,
                label: meshReady
                    ? '${controller.peerCount} nearby relay${controller.peerCount == 1 ? '' : 's'}'
                    : controller.meshState == BitchatMeshState.unavailable
                        ? 'Mesh unavailable here'
                        : 'Mesh starting',
                active: meshReady,
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _ModeControls extends StatelessWidget {
  const _ModeControls({required this.controller});

  final BitchatController controller;

  @override
  Widget build(BuildContext context) {
    final Widget modes = SegmentedButton<BitchatMode>(
      showSelectedIcon: false,
      segments: const <ButtonSegment<BitchatMode>>[
        ButtonSegment<BitchatMode>(value: BitchatMode.server, label: Text('Server')),
        ButtonSegment<BitchatMode>(value: BitchatMode.hybrid, label: Text('Hybrid')),
        ButtonSegment<BitchatMode>(value: BitchatMode.mesh, label: Text('Mesh')),
      ],
      selected: <BitchatMode>{controller.mode},
      onSelectionChanged: (Set<BitchatMode> value) {
        controller.setMode(value.first);
      },
    );
    final Widget timer = PopupMenuButton<int>(
      tooltip: 'Choose message burn time',
      onSelected: controller.setTtl,
      itemBuilder: (_) => (controller.session?.ttlOptions ?? <int>[3600])
          .map(
            (int seconds) => PopupMenuItem<int>(
              value: seconds,
              child: Text('Burn after ${_ttlLabel(seconds)}'),
            ),
          )
          .toList(growable: false),
      child: Container(
        height: 48,
        padding: const EdgeInsets.symmetric(horizontal: 11),
        decoration: BoxDecoration(
          color: AppColors.surfaceMuted,
          borderRadius: BorderRadius.circular(12),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            const Icon(Icons.timer_outlined, size: 17),
            const SizedBox(width: 5),
            Text(
              _ttlLabel(controller.ttlSeconds),
              style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 12),
            ),
          ],
        ),
      ),
    );
    return LayoutBuilder(
      builder: (BuildContext context, BoxConstraints constraints) {
        final bool stack = constraints.maxWidth < 440 ||
            MediaQuery.textScalerOf(context).scale(14) > 20;
        if (stack) {
          return Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              modes,
              const SizedBox(height: 7),
              Align(alignment: Alignment.centerRight, child: timer),
            ],
          );
        }
        return Row(
          children: <Widget>[
            Expanded(child: modes),
            const SizedBox(width: 9),
            timer,
          ],
        );
      },
    );
  }
}

class _TransportState extends StatelessWidget {
  const _TransportState({
    required this.icon,
    required this.label,
    required this.active,
  });

  final IconData icon;
  final String label;
  final bool active;

  @override
  Widget build(BuildContext context) => Expanded(
        child: Row(
          children: <Widget>[
            Icon(
              icon,
              size: 15,
              color: active ? AppColors.lime : AppColors.textFaint,
            ),
            const SizedBox(width: 5),
            Expanded(
              child: Text(
                label,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  color: active ? AppColors.ink : AppColors.textFaint,
                  fontSize: 10.5,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
          ],
        ),
      );
}

class _ChatError extends StatelessWidget {
  const _ChatError({required this.error, required this.onRetry});

  final Object error;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) => Container(
        margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
        padding: const EdgeInsets.fromLTRB(12, 8, 8, 8),
        decoration: BoxDecoration(
          color: const Color(0xFFFFF5F7),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: const Color(0xFFFFD8E0)),
        ),
        child: Row(
          children: <Widget>[
            const Icon(Icons.info_outline_rounded, color: AppColors.rose, size: 18),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                errorMessage(error),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontSize: 11.5),
              ),
            ),
            TextButton(onPressed: onRetry, child: const Text('Retry')),
          ],
        ),
      );
}

class _MessageList extends StatelessWidget {
  const _MessageList({
    required this.messages,
    required this.peerAlias,
    required this.scrollController,
  });

  final List<BitchatMessage> messages;
  final String peerAlias;
  final ScrollController scrollController;

  @override
  Widget build(BuildContext context) {
    if (messages.isEmpty) {
      return const EmptyState(
        icon: Icons.mode_comment_outlined,
        title: 'Nothing to retain',
        message:
            'Messages appear only on these devices, then burn on the timer you choose.',
      );
    }
    return Semantics(
      liveRegion: true,
      label: '${messages.length} unexpired messages',
      child: ListView.builder(
        controller: scrollController,
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 18),
        itemCount: messages.length,
        itemBuilder: (BuildContext context, int index) {
          final BitchatMessage message = messages[index];
          return _MessageBubble(message: message, peerAlias: peerAlias);
        },
      ),
    );
  }
}

class _MessageBubble extends StatelessWidget {
  const _MessageBubble({required this.message, required this.peerAlias});

  final BitchatMessage message;
  final String peerAlias;

  @override
  Widget build(BuildContext context) {
    final Duration remaining = message.expiresAt.difference(DateTime.now().toUtc());
    final String burn = _remainingLabel(remaining);
    final Color background = message.isMine ? AppColors.ink : AppColors.surface;
    final Color foreground = message.isMine ? Colors.white : AppColors.ink;
    return Semantics(
      label:
          '${message.isMine ? 'You' : peerAlias} said ${message.text}. Burns in $burn.',
      child: Align(
        alignment: message.isMine ? Alignment.centerRight : Alignment.centerLeft,
        child: Container(
          constraints: const BoxConstraints(maxWidth: 540),
          margin: const EdgeInsets.only(bottom: 9),
          padding: const EdgeInsets.fromLTRB(13, 10, 11, 8),
          decoration: BoxDecoration(
            color: background,
            border: Border.all(
              color: message.isMine ? AppColors.ink : AppColors.line,
            ),
            borderRadius: BorderRadius.only(
              topLeft: const Radius.circular(16),
              topRight: const Radius.circular(16),
              bottomLeft: Radius.circular(message.isMine ? 16 : 4),
              bottomRight: Radius.circular(message.isMine ? 4 : 16),
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Text(message.text, style: TextStyle(color: foreground, height: 1.35)),
              const SizedBox(height: 5),
              Row(
                mainAxisSize: MainAxisSize.min,
                children: <Widget>[
                  Icon(
                    Icons.local_fire_department_outlined,
                    size: 12,
                    color: message.isMine ? const Color(0xFFB8B5AE) : AppColors.textFaint,
                  ),
                  const SizedBox(width: 3),
                  Text(
                    burn,
                    style: TextStyle(
                      color: message.isMine ? const Color(0xFFB8B5AE) : AppColors.textFaint,
                      fontSize: 9.5,
                      fontFeatures: const <FontFeature>[FontFeature.tabularFigures()],
                    ),
                  ),
                  if (message.isMine) ...<Widget>[
                    const SizedBox(width: 7),
                    Icon(
                      _deliveryIcon(message.delivery),
                      size: 12,
                      color: message.delivery == BitchatDelivery.failed
                          ? AppColors.rose
                          : const Color(0xFFB8B5AE),
                    ),
                    const SizedBox(width: 3),
                    Text(
                      _deliveryLabel(message.delivery),
                      style: TextStyle(
                        color: message.delivery == BitchatDelivery.failed
                            ? const Color(0xFFFFA7B8)
                            : const Color(0xFFB8B5AE),
                        fontSize: 9.5,
                      ),
                    ),
                  ],
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _Composer extends StatelessWidget {
  const _Composer({
    required this.controller,
    required this.enabled,
    required this.sending,
    required this.peerReady,
    required this.onSend,
  });

  final TextEditingController controller;
  final bool enabled;
  final bool sending;
  final bool peerReady;
  final VoidCallback onSend;

  @override
  Widget build(BuildContext context) => Material(
        color: AppColors.surface,
        shape: const Border(top: BorderSide(color: AppColors.line)),
        child: Align(
          alignment: Alignment.topCenter,
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 760),
            child: Padding(
              padding: const EdgeInsets.fromLTRB(12, 9, 12, 9),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: <Widget>[
                  Expanded(
                    child: TextField(
                      controller: controller,
                      enabled: enabled && !sending,
                      minLines: 1,
                      maxLines: 5,
                      maxLength: 1500,
                      textCapitalization: TextCapitalization.sentences,
                      textInputAction: TextInputAction.newline,
                      decoration: InputDecoration(
                        hintText: !peerReady
                            ? 'Waiting for peer keys…'
                            : enabled
                                ? 'Write an encrypted message'
                                : 'This conversation is read-only',
                        counterText: '',
                        prefixIcon: const Icon(Icons.lock_outline_rounded, size: 19),
                      ),
                      onSubmitted: (_) => onSend(),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Semantics(
                    button: true,
                    label: 'Send encrypted message',
                    child: IconButton.filled(
                      tooltip: 'Send encrypted message',
                      onPressed: enabled && !sending ? onSend : null,
                      style: IconButton.styleFrom(
                        minimumSize: const Size.square(50),
                        backgroundColor: AppColors.violet,
                        foregroundColor: Colors.white,
                      ),
                      icon: sending
                          ? const SizedBox.square(
                              dimension: 18,
                              child: CircularProgressIndicator(
                                strokeWidth: 2,
                                color: Colors.white,
                              ),
                            )
                          : const Icon(Icons.arrow_upward_rounded),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      );
}

class _SecuritySheet extends StatelessWidget {
  const _SecuritySheet();

  @override
  Widget build(BuildContext context) => Padding(
        padding: EdgeInsets.fromLTRB(
          20,
          4,
          20,
          MediaQuery.viewPaddingOf(context).bottom + 28,
        ),
        child: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              Text('Private by construction', style: Theme.of(context).textTheme.headlineSmall),
              const SizedBox(height: 5),
              const Text(
                'Bitchat does not ask the server to keep a secret it never needed to know.',
                style: TextStyle(color: AppColors.textMuted),
              ),
              const SizedBox(height: 18),
              const _SecurityFact(
                icon: Icons.key_rounded,
                title: 'One-time X25519 prekeys',
                detail:
                    'Every recipient device publishes signed one-time public keys. The private half is destroyed after authenticated decryption.',
              ),
              const _SecurityFact(
                icon: Icons.verified_user_outlined,
                title: 'Ed25519 identity signatures',
                detail:
                    'A relay cannot alter the sender, room, timer, hop budget or ciphertext without the recipient rejecting it.',
              ),
              const _SecurityFact(
                icon: Icons.security_rounded,
                title: 'AES-256-GCM on the device',
                detail:
                    'The server stores opaque ciphertext only. Local messages are also encrypted with a separate Keychain/Keystore vault key.',
              ),
              const _SecurityFact(
                icon: Icons.bluetooth_searching_rounded,
                title: 'Store-and-forward BLE mesh',
                detail:
                    'Hybrid mode sends by internet and Bluetooth. Nearby devices relay encrypted fragments with deduplication, expiry and a three-hop ceiling.',
              ),
              const _SecurityFact(
                icon: Icons.local_fire_department_outlined,
                title: 'Physical expiry',
                detail:
                    'The visible burn timer is the real envelope expiry. Both the local vault and server sweeper delete expired ciphertext.',
              ),
              const _SecurityFact(
                icon: Icons.sos_rounded,
                title: 'Panic means destruction',
                detail:
                    'The panic control logs only that an emergency happened, alerts safety, revokes this device identity and erases queued ciphertext and local keys.',
              ),
            ],
          ),
        ),
      );
}

class _SecurityFact extends StatelessWidget {
  const _SecurityFact({
    required this.icon,
    required this.title,
    required this.detail,
  });

  final IconData icon;
  final String title;
  final String detail;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 16),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Container(
              width: 42,
              height: 42,
              decoration: const BoxDecoration(
                color: AppColors.paleViolet,
                shape: BoxShape.circle,
              ),
              child: Icon(icon, color: AppColors.violetInk, size: 21),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Text(title, style: const TextStyle(fontWeight: FontWeight.w800)),
                  const SizedBox(height: 3),
                  Text(
                    detail,
                    style: const TextStyle(color: AppColors.textMuted, height: 1.35),
                  ),
                ],
              ),
            ),
          ],
        ),
      );
}

String _ttlLabel(int seconds) => switch (seconds) {
      10 => '10 sec',
      60 => '1 min',
      3600 => '1 hour',
      86400 => '1 day',
      604800 => '7 days',
      _ => '${seconds}s',
    };

String _remainingLabel(Duration value) {
  if (value.inSeconds <= 0) return 'burned';
  if (value.inDays > 0) return '${value.inDays}d ${value.inHours.remainder(24)}h';
  if (value.inHours > 0) return '${value.inHours}h ${value.inMinutes.remainder(60)}m';
  if (value.inMinutes > 0) return '${value.inMinutes}m ${value.inSeconds.remainder(60)}s';
  return '${value.inSeconds}s';
}

IconData _deliveryIcon(BitchatDelivery delivery) => switch (delivery) {
      BitchatDelivery.sending => Icons.schedule_rounded,
      BitchatDelivery.server => Icons.cloud_done_outlined,
      BitchatDelivery.mesh => Icons.bluetooth_connected_rounded,
      BitchatDelivery.hybrid => Icons.done_all_rounded,
      BitchatDelivery.failed => Icons.error_outline_rounded,
    };

String _deliveryLabel(BitchatDelivery delivery) => switch (delivery) {
      BitchatDelivery.sending => 'sealing',
      BitchatDelivery.server => 'relay',
      BitchatDelivery.mesh => 'mesh',
      BitchatDelivery.hybrid => 'hybrid',
      BitchatDelivery.failed => 'failed',
    };
