/// Talk about a photo (find 1.1), on an image result's detail pane or sheet: Describe, Ask about this photo,
/// Compare with… another image result, and the streamed answer, labelled as Find's reading of the photo, with
/// Copy, Keep this description (Describe only) and Stop. "Deeper analysis" (the deeper model) is offered on Ask,
/// with its live cost or why not now (both from vision_state).
///
/// Answers and file names are shown as plain text only (Text widgets): never read as markdown or HTML.
/// Keys: Enter in the question field asks; Esc stops a running answer before it closes anything (search_screen).
library;

import 'dart:async';

import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';

import '../../app/scope.dart';
import '../../app/theme/colors.dart';
import '../../app/theme/tokens.dart';
import '../../app/theme/typography.dart';
import '../../engine/models/result.dart';
import '../../state/talk_controller.dart';
import '../../widgets/controls.dart';
import '../../widgets/icons.dart';

/// The answer area's label: what is shown is the model's reading, not a fact about the photo.
const talkLabel = "Find's reading of this photo";

class TalkPanel extends StatefulWidget {
  const TalkPanel({super.key, required this.talk, required this.photo, this.others = const []});
  final TalkController talk;
  final FileResult photo;

  /// The other image results in the list now (Compare with…).
  final List<FileResult> others;

  @override
  State<TalkPanel> createState() => _TalkPanelState();
}

class _TalkPanelState extends State<TalkPanel> {
  final _q = TextEditingController();
  final _qFocus = FocusNode(debugLabel: 'question about the photo');
  final _compare = MenuController();
  bool _deeper = false;

  @override
  void initState() {
    super.initState();
    widget.talk.show(widget.photo.id);
  }

  @override
  void didUpdateWidget(TalkPanel old) {
    super.didUpdateWidget(old);
    if (old.photo.id != widget.photo.id) {
      _q.clear();
      _deeper = false;
      widget.talk.show(widget.photo.id);
    }
  }

  @override
  void dispose() {
    _q.dispose();
    _qFocus.dispose();
    super.dispose();
  }

  void _ask() {
    final t = widget.talk;
    final offer = t.deeperOffer;
    unawaited(t.ask(_q.text, deeper: _deeper && offer != null && offer.available));
  }

  KeyEventResult _keys(FocusNode node, KeyEvent e) {
    final k = e.logicalKey;
    if (k != LogicalKeyboardKey.enter && k != LogicalKeyboardKey.numpadEnter) return KeyEventResult.ignored;
    if (e is KeyDownEvent && !HardwareKeyboard.instance.isControlPressed && !HardwareKeyboard.instance.isShiftPressed) {
      _ask();
    }
    return KeyEventResult.handled;
  }

  void _copy() {
    unawaited(Clipboard.setData(ClipboardData(text: widget.talk.text)));
    AppScope.of(context).toasts.show('Copied the answer');
  }

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return ListenableBuilder(
      listenable: widget.talk,
      builder: (context, _) {
        final t = widget.talk;
        if (!t.served || t.state == null) return const SizedBox.shrink(); // not until the engine says it can
        final blocked = t.notNow.isNotEmpty;
        final offer = t.deeperOffer;
        return Column(
          key: const ValueKey('talk'),
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Container(height: 1, color: c.line, margin: const EdgeInsets.only(bottom: 12)),
            Text('Talk about this photo', style: NbType.text(12.5, c.muted, weight: FontWeight.w600)),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                NbButton(
                  'Describe',
                  small: true,
                  kind: NbButtonKind.ghost,
                  icon: NbGlyph.image,
                  onPressed: blocked ? null : () => unawaited(t.describe()),
                ),
                MenuAnchor(
                  controller: _compare,
                  menuChildren: [
                    for (final o in widget.others)
                      MenuItemButton(
                        onPressed: () => unawaited(t.compare(o.id, question: _q.text)),
                        leadingIcon: NbIcon(NbGlyph.image, size: 15, color: c.muted),
                        child: ConstrainedBox(
                          constraints: const BoxConstraints(maxWidth: 260),
                          child: Text(
                            o.name,
                            overflow: TextOverflow.ellipsis,
                            style: NbType.text(13, c.text),
                          ),
                        ),
                      ),
                  ],
                  child: NbButton(
                    'Compare with…',
                    small: true,
                    kind: NbButtonKind.ghost,
                    onPressed: blocked || widget.others.isEmpty ? null : () => _compare.open(),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            // Enter asks (it would open the result otherwise); the text keys stay the field's own
            DefaultTextEditingShortcuts(
              child: Focus(
                canRequestFocus: false,
                skipTraversal: true,
                onKeyEvent: _keys,
                child: Semantics(
                  label: 'Ask about this photo',
                  textField: true,
                  child: TextField(
                    controller: _q,
                    focusNode: _qFocus,
                    enabled: !blocked,
                    maxLength: 2000,
                    maxLengthEnforcement: MaxLengthEnforcement.enforced,
                    style: NbType.text(13, c.text),
                    cursorColor: c.orange,
                    decoration: InputDecoration(
                      isDense: true,
                      filled: true,
                      counterText: '',
                      fillColor: c.raised,
                      hintText: 'Ask about this photo',
                      hintStyle: NbType.text(13, c.dim),
                      contentPadding: const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
                      enabledBorder: OutlineInputBorder(
                        borderRadius: NbRadius.controlAll,
                        borderSide: BorderSide(color: c.line2),
                      ),
                      disabledBorder: OutlineInputBorder(
                        borderRadius: NbRadius.controlAll,
                        borderSide: BorderSide(color: c.line),
                      ),
                      focusedBorder: OutlineInputBorder(
                        borderRadius: NbRadius.controlAll,
                        borderSide: BorderSide(color: c.orange),
                      ),
                    ),
                  ),
                ),
              ),
            ),
            if (offer != null) ...[
              const SizedBox(height: 8),
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Padding(
                    padding: const EdgeInsets.only(top: 1),
                    child: NbSwitch(
                      value: _deeper && offer.available,
                      label: offer.label,
                      onChanged: offer.available ? (v) => setState(() => _deeper = v) : null,
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(offer.label, style: NbType.text(12.5, offer.available ? c.text : c.dim)),
                        Text(offer.detail, style: NbType.text(11.5, c.dim, height: 1.4)),
                      ],
                    ),
                  ),
                ],
              ),
            ],
            if (blocked) ...[
              const SizedBox(height: 8),
              Text(t.notNow, style: NbType.text(12, c.muted, height: 1.4)),
            ],
            if (t.phase != TalkPhase.idle) ...[const SizedBox(height: 12), _Answer(talk: t, onCopy: _copy)],
          ],
        );
      },
    );
  }
}

/// The answer: its label, the text as it streams (replaced as it grows), its notes and what can be done with it.
class _Answer extends StatelessWidget {
  const _Answer({required this.talk, required this.onCopy});
  final TalkController talk;
  final VoidCallback onCopy;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final t = talk;
    final note = NbType.text(11.5, c.dim, height: 1.4);
    final failed = t.phase == TalkPhase.failed;
    final children = <Widget>[];
    if (!failed) {
      children.add(Text(talkLabel, style: NbType.text(NbSize.micro + .5, c.dim, weight: FontWeight.w600)));
      children.add(const SizedBox(height: 6));
    }
    if (t.phase == TalkPhase.starting) {
      children.add(Text('Starting…', style: note));
    } else if (t.phase == TalkPhase.loading) {
      children.add(Text(t.loadingLine, style: note));
    } else if (t.phase == TalkPhase.answering && t.text.isEmpty) {
      children.add(Text('Looking at the photo…', style: note));
    }
    if (!failed && t.text.isNotEmpty) {
      // plain text: an answer is never read as markdown or HTML
      children.add(SelectableText(t.text, style: NbType.text(13, c.text, height: 1.5)));
    }
    if (t.textOnly) {
      children.add(const SizedBox(height: 4));
      children.add(Text(textReadNote, style: note));
    }
    if (t.unverified) {
      children.add(const SizedBox(height: 4));
      children.add(Text('may not be exact; the text read from the photo is above', style: note));
    }
    if (t.phase == TalkPhase.stopped && t.note.isNotEmpty) {
      children.add(const SizedBox(height: 4));
      children.add(Text(t.note, style: NbType.text(12, c.muted, height: 1.4)));
    }
    if (failed) children.add(Text(t.error, style: NbType.text(12.5, c.danger, height: 1.4)));
    if (!failed && t.error.isNotEmpty) children.add(Text(t.error, style: NbType.text(12, c.danger, height: 1.4)));
    final actions = <Widget>[
      if (t.running) NbButton('Stop', small: true, kind: NbButtonKind.ghost, icon: NbGlyph.close, onPressed: t.stop),
      if (!t.running && !failed && t.text.isNotEmpty)
        NbButton('Copy', small: true, kind: NbButtonKind.ghost, icon: NbGlyph.copy, onPressed: onCopy),
      if (t.canKeep)
        NbButton(
          t.kept ? 'Kept' : 'Keep this description',
          small: true,
          kind: NbButtonKind.ghost,
          icon: t.kept ? NbGlyph.check : null,
          onPressed: t.kept || t.keeping ? null : () => unawaited(t.keep()),
        ),
      if (t.textOnly)
        NbButton('Ask the model too', small: true, kind: NbButtonKind.ghost, onPressed: () => unawaited(t.askModelToo())),
    ];
    if (actions.isNotEmpty) {
      children.add(const SizedBox(height: 10));
      children.add(Wrap(spacing: 8, runSpacing: 8, children: actions));
    }
    return Semantics(
      container: true,
      liveRegion: true,
      label: failed ? null : talkLabel,
      // a rule on the left marks the reading (no box: the pane is narrow and the buttons need its width)
      child: Container(
        padding: const EdgeInsets.fromLTRB(10, 2, 0, 2),
        decoration: BoxDecoration(
          border: Border(left: BorderSide(color: c.orangeA(.55), width: 2)),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: children),
      ),
    );
  }
}
