import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../../core/theme/app_theme.dart';
import '../../data/models/models.dart';
import '../../data/repositories/karma_repository.dart';
import '../../data/services/device_capabilities_service.dart';
import '../../shared/widgets/primitives.dart';
import '../auth/session_controller.dart';
import 'post_card.dart';

class FeedScreen extends StatefulWidget {
  const FeedScreen({
    required this.onHire,
    super.key,
    this.refreshSignal = 0,
  });

  final ValueChanged<PostModel> onHire;
  final int refreshSignal;

  @override
  State<FeedScreen> createState() => _FeedScreenState();
}

class _FeedScreenState extends State<FeedScreen>
    with AutomaticKeepAliveClientMixin<FeedScreen> {
  List<PostModel>? _posts;
  Object? _error;
  bool _proofOnly = false;
  bool _fromCache = false;
  int _loadRevision = 0;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(FeedScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.refreshSignal != widget.refreshSignal) _load();
  }

  Future<void> _load() async {
    final User? user = context.read<SessionController>().user;
    if (user == null) return;
    final int revision = ++_loadRevision;
    final bool requestedProofOnly = _proofOnly;
    setState(() => _error = null);
    try {
      final FeedPage page = await context.read<KarmaRepository>().posts(
            userId: user.id,
            proofOnly: requestedProofOnly,
          );
      if (!mounted ||
          revision != _loadRevision ||
          requestedProofOnly != _proofOnly) {
        return;
      }
      setState(() {
        _posts = page.posts;
        _fromCache = page.fromCache;
      });
    } on Object catch (error) {
      if (!mounted ||
          revision != _loadRevision ||
          requestedProofOnly != _proofOnly) {
        return;
      }
      setState(() => _error = error);
    }
  }

  void _updatePost(PostModel updated) {
    setState(() {
      _posts = _posts
          ?.map((PostModel post) => post.id == updated.id ? updated : post)
          .toList(growable: false);
    });
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final User user = context.watch<SessionController>().user!;
    return RefreshIndicator(
      onRefresh: _load,
      edgeOffset: 8,
      child: CustomScrollView(
        key: const PageStorageKey<String>('feed'),
        physics: const AlwaysScrollableScrollPhysics(),
        slivers: <Widget>[
          SliverToBoxAdapter(
            child: ContentRail(
              padding: const EdgeInsets.fromLTRB(16, 14, 16, 8),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Text(
                    _greeting(user.displayName),
                    style: Theme.of(context).textTheme.headlineSmall,
                  ),
                  const SizedBox(height: 3),
                  const Text(
                    'Real work. Real people. Receipts included.',
                    style: TextStyle(color: AppColors.textMuted),
                  ),
                  const SizedBox(height: 16),
                  Row(
                    children: <Widget>[
                      ChoiceChip(
                        label: const Text('Everything'),
                        selected: !_proofOnly,
                        onSelected: (_) {
                          setState(() {
                            _proofOnly = false;
                            _posts = null;
                          });
                          _load();
                        },
                      ),
                      const SizedBox(width: 8),
                      ChoiceChip(
                        avatar: const Icon(Icons.verified_outlined, size: 17),
                        label: const Text('Proof of work'),
                        selected: _proofOnly,
                        onSelected: (_) {
                          setState(() {
                            _proofOnly = true;
                            _posts = null;
                          });
                          _load();
                        },
                      ),
                    ],
                  ),
                  if (_fromCache) ...<Widget>[
                    const SizedBox(height: 12),
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
                      decoration: BoxDecoration(
                        color: AppColors.paleGold,
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: const Row(
                        children: <Widget>[
                          Icon(Icons.cloud_off_outlined, color: AppColors.gold, size: 18),
                          SizedBox(width: 8),
                          Expanded(
                            child: Text(
                              'Offline · showing your last saved feed',
                              style: TextStyle(
                                color: AppColors.gold,
                                fontWeight: FontWeight.w600,
                                fontSize: 12.5,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ),
          if (_error != null)
            SliverToBoxAdapter(
              child: ContentRail(
                child: ErrorPanel(message: errorMessage(_error!), onRetry: _load),
              ),
            )
          else if (_posts == null)
            const SliverToBoxAdapter(
              child: ContentRail(child: LoadingCards(count: 3)),
            )
          else if (_posts!.isEmpty)
            SliverToBoxAdapter(
              child: ContentRail(
                child: EmptyState(
                  icon: _proofOnly ? Icons.verified_outlined : Icons.dynamic_feed_outlined,
                  title: _proofOnly ? 'No proof yet' : 'A quiet feed',
                  message: _proofOnly
                      ? 'Completed paid gigs become permanent proof here.'
                      : 'Share the first useful thing with your community.',
                ),
              ),
            )
          else
            SliverPadding(
              padding: const EdgeInsets.fromLTRB(16, 4, 16, 112),
              sliver: SliverList.separated(
                itemCount: _posts!.length,
                separatorBuilder: (_, __) => const SizedBox(height: 14),
                itemBuilder: (BuildContext context, int index) {
                  final PostModel post = _posts![index];
                  return Align(
                    alignment: Alignment.topCenter,
                    child: ConstrainedBox(
                      constraints: const BoxConstraints(maxWidth: AppTheme.contentMaxWidth),
                      child: PostCard(
                        key: ValueKey<int>(post.id),
                        post: post,
                        onChanged: _updatePost,
                        onHire: widget.onHire,
                      ),
                    ),
                  );
                },
              ),
            ),
        ],
      ),
    );
  }

  static String _greeting(String name) {
    final int hour = DateTime.now().hour;
    final String time = hour < 12
        ? 'Good morning'
        : hour < 17
            ? 'Good afternoon'
            : 'Good evening';
    final String firstName = name.trim().split(RegExp(r'\s+')).first;
    return '$time, $firstName';
  }
}

Future<bool> showComposePostSheet(BuildContext context) async {
  final bool? result = await showModalBottomSheet<bool>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    showDragHandle: true,
    builder: (BuildContext context) => const _ComposePostSheet(),
  );
  return result ?? false;
}

class _ComposePostSheet extends StatefulWidget {
  const _ComposePostSheet();

  @override
  State<_ComposePostSheet> createState() => _ComposePostSheetState();
}

class _ComposePostSheetState extends State<_ComposePostSheet> {
  final TextEditingController _body = TextEditingController();
  final DeviceCapabilitiesService _device = DeviceCapabilitiesService();
  PendingImage? _image;
  String? _uploadedUrl;
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _body.dispose();
    super.dispose();
  }

  Future<void> _chooseImage() async {
    try {
      final PendingImage? image = await _device.pickImage(context);
      if (image != null && mounted) {
        setState(() {
          _image = image;
          _uploadedUrl = null;
        });
      }
    } on Object catch (error) {
      if (mounted) setState(() => _error = errorMessage(error));
    }
  }

  Future<void> _publish() async {
    if (_body.text.trim().isEmpty && _image == null) {
      setState(() => _error = 'Write something or attach a photo.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final KarmaRepository repository = context.read<KarmaRepository>();
      String? mediaUrl = _uploadedUrl;
      if (_image != null && mediaUrl == null) {
        final UploadedMedia uploaded = await repository.uploadMedia(
          bytes: _image!.bytes,
          filename: _image!.name,
          purpose: 'post',
        );
        mediaUrl = uploaded.url;
        _uploadedUrl = mediaUrl;
      }
      await repository.createPost(
            body: _body.text,
            mediaUrls: mediaUrl == null ? const <String>[] : <String>[mediaUrl],
          );
      HapticFeedback.mediumImpact();
      if (mounted) Navigator.pop(context, true);
    } on Object catch (error) {
      if (mounted) setState(() => _error = errorMessage(error));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final User user = context.watch<SessionController>().user!;
    return Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(context).bottom),
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(20, 4, 20, 24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            Row(
              children: <Widget>[
                UserAvatar(name: user.displayName, url: user.avatarUrl, radius: 20),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: <Widget>[
                      Text(user.displayName, style: const TextStyle(fontWeight: FontWeight.w700)),
                      Text(
                        '@${user.handle}',
                        style: const TextStyle(color: AppColors.textFaint, fontSize: 12.5),
                      ),
                    ],
                  ),
                ),
                TextButton(
                  onPressed: _busy ? null : _publish,
                  child: const Text('Publish'),
                ),
              ],
            ),
            const SizedBox(height: 14),
            TextField(
              controller: _body,
              autofocus: true,
              minLines: 4,
              maxLines: 10,
              maxLength: 4000,
              textCapitalization: TextCapitalization.sentences,
              decoration: const InputDecoration(
                hintText: 'Share something useful…\nHashtags are picked up automatically.',
                alignLabelWithHint: true,
              ),
            ),
            const SizedBox(height: 10),
            if (_image != null) ...<Widget>[
              ClipRRect(
                borderRadius: BorderRadius.circular(14),
                child: AspectRatio(
                  aspectRatio: 16 / 9,
                  child: Image.memory(_image!.bytes, fit: BoxFit.cover),
                ),
              ),
              const SizedBox(height: 8),
            ],
            OutlinedButton.icon(
              onPressed: _busy ? null : _chooseImage,
              icon: Icon(_image == null ? Icons.add_a_photo_outlined : Icons.swap_horiz_rounded),
              label: Text(_image == null ? 'Add photo' : 'Choose another photo'),
            ),
            if (_image != null)
              TextButton.icon(
                onPressed: _busy
                    ? null
                    : () => setState(() {
                          _image = null;
                          _uploadedUrl = null;
                        }),
                icon: const Icon(Icons.close_rounded),
                label: const Text('Remove photo'),
              ),
            if (_error != null) ...<Widget>[
              const SizedBox(height: 10),
              Text(
                _error!,
                style: const TextStyle(color: AppColors.rose, fontWeight: FontWeight.w600),
              ),
            ],
            const SizedBox(height: 16),
            FilledButton.icon(
              onPressed: _busy ? null : _publish,
              icon: _busy
                  ? const SizedBox.square(
                      dimension: 18,
                      child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                    )
                  : const Icon(Icons.arrow_upward_rounded),
              label: Text(_busy ? 'Publishing…' : 'Share update'),
            ),
            const SizedBox(height: 10),
            const Text(
              'Proof posts cannot be composed. They are published automatically from completed, paid gigs.',
              textAlign: TextAlign.center,
              style: TextStyle(color: AppColors.textFaint, fontSize: 11.5, height: 1.4),
            ),
          ],
        ),
      ),
    );
  }
}
