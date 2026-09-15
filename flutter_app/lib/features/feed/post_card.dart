import 'dart:ui' show FontFeature;
import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../../core/theme/app_theme.dart';
import '../../core/utils/formatters.dart';
import '../../data/models/models.dart';
import '../../data/repositories/karma_repository.dart';
import '../../shared/widgets/primitives.dart';
import '../../shared/widgets/proof_comparison.dart';

class PostCard extends StatefulWidget {
  const PostCard({
    required this.post,
    required this.onChanged,
    required this.onHire,
    super.key,
  });

  final PostModel post;
  final ValueChanged<PostModel> onChanged;
  final ValueChanged<PostModel> onHire;

  @override
  State<PostCard> createState() => _PostCardState();
}

class _PostCardState extends State<PostCard> {
  bool _liked = false;
  bool _liking = false;

  Future<void> _toggleLike() async {
    if (_liking) return;
    final bool previous = _liked;
    setState(() {
      _liking = true;
      _liked = !previous;
    });
    HapticFeedback.selectionClick();
    try {
      final PostModel result = await context
          .read<KarmaRepository>()
          .toggleLike(widget.post.id);
      widget.onChanged(result);
    } on Object catch (error) {
      if (!mounted) return;
      setState(() => _liked = previous);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(errorMessage(error))),
      );
    } finally {
      if (mounted) setState(() => _liking = false);
    }
  }

  Future<void> _openComments() async {
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      showDragHandle: true,
      builder: (BuildContext context) => CommentsSheet(
        postId: widget.post.id,
        onCommentAdded: () {
          widget.onChanged(
            widget.post.copyWith(
              commentsCount: widget.post.commentsCount + 1,
            ),
          );
        },
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final PostModel post = widget.post;
    final String name = post.authorName ?? 'KARMA member';
    return KarmaCard(
      padding: EdgeInsets.zero,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 12),
            child: Row(
              children: <Widget>[
                UserAvatar(name: name, url: post.authorAvatar),
                const SizedBox(width: 11),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: <Widget>[
                      Row(
                        children: <Widget>[
                          Flexible(
                            child: Text(
                              name,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(fontWeight: FontWeight.w700),
                            ),
                          ),
                          if (post.authorTier != null && post.authorTier != 'none') ...<Widget>[
                            const SizedBox(width: 7),
                            TierBadge(tier: post.authorTier!),
                          ],
                        ],
                      ),
                      const SizedBox(height: 2),
                      Text(
                        '@${post.authorHandle ?? 'member'} · ${relativeTime(post.createdAt)}'
                        '${post.authorKarma == null ? '' : ' · ${post.authorKarma} karma'}',
                        style: const TextStyle(
                          color: AppColors.textFaint,
                          fontSize: 12.5,
                        ),
                      ),
                    ],
                  ),
                ),
                if (post.isProof)
                  const Tooltip(
                    message: 'Verified paid gig',
                    child: Icon(Icons.verified_rounded, color: AppColors.lime, size: 22),
                  ),
              ],
            ),
          ),
          if (post.isProof && post.beforeUrl != null && post.afterUrl != null)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12),
              child: ProofComparison(
                beforeUrl: post.beforeUrl!,
                afterUrl: post.afterUrl!,
              ),
            )
          else if (post.mediaUrls.isNotEmpty)
            _PostImage(url: post.mediaUrls.first),
          if (post.body.isNotEmpty || post.hashtags.isNotEmpty)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 14, 16, 12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  if (post.body.isNotEmpty)
                    Text(post.body, style: const TextStyle(fontSize: 15.5, height: 1.45)),
                  if (post.hashtags.isNotEmpty) ...<Widget>[
                    const SizedBox(height: 6),
                    Wrap(
                      spacing: 6,
                      runSpacing: 4,
                      children: post.hashtags
                          .map(
                            (String hashtag) => Text(
                              '#$hashtag',
                              style: const TextStyle(
                                color: AppColors.violetInk,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                          )
                          .toList(growable: false),
                    ),
                  ],
                ],
              ),
            ),
          if (post.isProof)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                decoration: BoxDecoration(
                  color: AppColors.surfaceMuted,
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Wrap(
                  spacing: 14,
                  runSpacing: 7,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: <Widget>[
                    if (post.rating != null)
                      Row(
                        mainAxisSize: MainAxisSize.min,
                        children: <Widget>[
                          const Icon(Icons.star_rounded, color: AppColors.gold, size: 18),
                          Text(
                            '${post.rating}/5',
                            style: const TextStyle(
                              color: AppColors.gold,
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                        ],
                      ),
                    if (post.amountEarned != null)
                      Text(
                        '${inr(post.amountEarned!)} earned',
                        style: const TextStyle(
                          color: AppColors.textMuted,
                          fontWeight: FontWeight.w600,
                          fontFeatures: <FontFeature>[FontFeature.tabularFigures()],
                        ),
                      ),
                    const Row(
                      mainAxisSize: MainAxisSize.min,
                      children: <Widget>[
                        Icon(Icons.check_circle, color: AppColors.lime, size: 16),
                        SizedBox(width: 4),
                        Text(
                          'Verified gig',
                          style: TextStyle(
                            color: AppColors.lime,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
          const Divider(),
          Padding(
            padding: const EdgeInsets.fromLTRB(8, 3, 10, 7),
            child: Row(
              children: <Widget>[
                TextButton.icon(
                  onPressed: _liking ? null : _toggleLike,
                  icon: AnimatedScale(
                    duration: AppTheme.quick,
                    scale: _liked ? 1.12 : 1,
                    child: Icon(
                      _liked ? Icons.favorite_rounded : Icons.favorite_border_rounded,
                      color: _liked ? AppColors.rose : AppColors.textMuted,
                      size: 21,
                    ),
                  ),
                  label: Text(
                    post.likesCount.toString(),
                    style: TextStyle(
                      color: _liked ? AppColors.rose : AppColors.textMuted,
                    ),
                  ),
                ),
                TextButton.icon(
                  onPressed: _openComments,
                  icon: const Icon(Icons.mode_comment_outlined, size: 20),
                  label: Text(post.commentsCount.toString()),
                  style: TextButton.styleFrom(foregroundColor: AppColors.textMuted),
                ),
                const Spacer(),
                if (post.isProof)
                  FilledButton.icon(
                    onPressed: () => widget.onHire(post),
                    icon: const Icon(Icons.handyman_outlined, size: 18),
                    label: const Text('Hire'),
                    style: FilledButton.styleFrom(
                      minimumSize: const Size(0, 40),
                      padding: const EdgeInsets.symmetric(horizontal: 15),
                    ),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _PostImage extends StatelessWidget {
  const _PostImage({required this.url});

  final String url;

  @override
  Widget build(BuildContext context) => AspectRatio(
        aspectRatio: 4 / 3,
        child: CachedNetworkImage(
          imageUrl: url,
          fit: BoxFit.cover,
          placeholder: (_, __) => const ColoredBox(color: AppColors.surfaceMuted),
          errorWidget: (_, __, ___) => const ColoredBox(
            color: AppColors.surfaceMuted,
            child: Center(
              child: Icon(Icons.broken_image_outlined, color: AppColors.textFaint),
            ),
          ),
        ),
      );
}

class CommentsSheet extends StatefulWidget {
  const CommentsSheet({
    required this.postId,
    required this.onCommentAdded,
    super.key,
  });

  final int postId;
  final VoidCallback onCommentAdded;

  @override
  State<CommentsSheet> createState() => _CommentsSheetState();
}

class _CommentsSheetState extends State<CommentsSheet> {
  final TextEditingController _controller = TextEditingController();
  List<CommentModel>? _comments;
  Object? _error;
  bool _posting = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final List<CommentModel> result =
          await context.read<KarmaRepository>().comments(widget.postId);
      if (mounted) setState(() => _comments = result);
    } on Object catch (error) {
      if (mounted) setState(() => _error = error);
    }
  }

  Future<void> _post() async {
    if (_controller.text.trim().isEmpty || _posting) return;
    setState(() => _posting = true);
    try {
      await context
          .read<KarmaRepository>()
          .addComment(widget.postId, _controller.text);
      _controller.clear();
      if (!mounted) return;
      widget.onCommentAdded();
      await _load();
    } on Object catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(errorMessage(error))),
        );
      }
    } finally {
      if (mounted) setState(() => _posting = false);
    }
  }

  @override
  Widget build(BuildContext context) => Padding(
        padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(context).bottom),
        child: SizedBox(
          height: MediaQuery.sizeOf(context).height * 0.72,
          child: Column(
            children: <Widget>[
              Padding(
                padding: const EdgeInsets.fromLTRB(20, 4, 12, 12),
                child: Row(
                  children: <Widget>[
                    Expanded(
                      child: Text('Comments', style: Theme.of(context).textTheme.titleLarge),
                    ),
                    IconButton(
                      tooltip: 'Close comments',
                      onPressed: () => Navigator.pop(context),
                      icon: const Icon(Icons.close),
                    ),
                  ],
                ),
              ),
              const Divider(),
              Expanded(
                child: _error != null
                    ? Center(
                        child: TextButton.icon(
                          onPressed: () {
                            setState(() => _error = null);
                            _load();
                          },
                          icon: const Icon(Icons.refresh),
                          label: Text(errorMessage(_error!)),
                        ),
                      )
                    : _comments == null
                        ? const Center(child: CircularProgressIndicator())
                        : _comments!.isEmpty
                            ? const EmptyState(
                                icon: Icons.chat_bubble_outline,
                                title: 'Start the conversation',
                                message: 'Ask a useful question or celebrate the work.',
                              )
                            : ListView.separated(
                                padding: const EdgeInsets.all(16),
                                itemCount: _comments!.length,
                                separatorBuilder: (_, __) => const SizedBox(height: 12),
                                itemBuilder: (BuildContext context, int index) {
                                  final CommentModel comment = _comments![index];
                                  return Row(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: <Widget>[
                                      UserAvatar(name: comment.authorName, radius: 17),
                                      const SizedBox(width: 10),
                                      Expanded(
                                        child: Container(
                                          padding: const EdgeInsets.all(12),
                                          decoration: BoxDecoration(
                                            color: AppColors.surfaceMuted,
                                            borderRadius: BorderRadius.circular(12),
                                          ),
                                          child: Column(
                                            crossAxisAlignment: CrossAxisAlignment.start,
                                            children: <Widget>[
                                              Text(
                                                '${comment.authorName}  @${comment.authorHandle}',
                                                style: const TextStyle(
                                                  fontWeight: FontWeight.w700,
                                                  fontSize: 12.5,
                                                ),
                                              ),
                                              const SizedBox(height: 4),
                                              Text(comment.body),
                                            ],
                                          ),
                                        ),
                                      ),
                                    ],
                                  );
                                },
                              ),
              ),
              const Divider(),
              SafeArea(
                top: false,
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(16, 10, 10, 10),
                  child: Row(
                    children: <Widget>[
                      Expanded(
                        child: TextField(
                          controller: _controller,
                          maxLength: 2000,
                          maxLines: 3,
                          minLines: 1,
                          textInputAction: TextInputAction.send,
                          onSubmitted: (_) => _post(),
                          decoration: const InputDecoration(
                            hintText: 'Write a comment…',
                            counterText: '',
                          ),
                        ),
                      ),
                      const SizedBox(width: 6),
                      IconButton.filled(
                        tooltip: 'Post comment',
                        onPressed: _posting ? null : _post,
                        icon: _posting
                            ? const SizedBox.square(
                                dimension: 18,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                  color: Colors.white,
                                ),
                              )
                            : const Icon(Icons.send_rounded),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      );
}
