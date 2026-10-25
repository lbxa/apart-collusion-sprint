// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

contract Veracity {
    enum State {
        Unknown,
        Registered,
        Open,
        Commit,
        Reveal,
        SettledCreator,
        SettledChallenger,
        Aborted,
        ExpiredUnchallenged,
        ExpiredUnfunded
    }

    struct Config {
        address creator;
        address challenger;
        address[] jurors;
        address treasury;
        bytes32 configurationHash;
        uint256 beta;
        uint16 gammaBps;
        uint16 winnerBps;
        uint16 jurorBps;
        uint16 protocolBps;
        uint64 postingDuration;
        uint64 challengeDuration;
        uint64 commitDuration;
        uint64 revealDuration;
    }

    struct EpisodeView {
        Config config;
        bytes32 contentHash;
        bytes32 evidenceHash;
        uint64 postingDeadline;
        uint64 challengeDeadline;
        uint64 commitDeadline;
        uint64 revealDeadline;
        State state;
        uint8 creatorVotes;
        uint8 challengerVotes;
        uint256 jurorBond;
        uint256 lockedLiability;
        uint256 totalDeposited;
        uint256 totalCredited;
    }

    struct JurorVote {
        bytes32 commitment;
        bytes32 assessmentHash;
        bool revealed;
        uint8 verdict;
    }

    struct Settlement {
        State outcome;
        address winner;
        uint256 winnerPayout;
        uint256 jurorReward;
        uint256 protocolFee;
        uint256 forfeitedBonds;
    }

    error Unauthorized();
    error InvalidConfiguration();
    error UnknownEpisode();
    error DuplicateEpisode();
    error WrongPhase();
    error IncorrectDeposit();
    error InvalidHash();
    error DuplicateAction();
    error InvalidVerdict();
    error InvalidCommitment();
    error NothingToWithdraw();
    error TransferFailed();
    error ReentrantWithdrawal();

    uint256 public constant ABI_VERSION = 1;
    address public immutable operator;
    mapping(address => uint256) public credits;
    mapping(bytes32 => mapping(address => uint256)) public entitlement;
    uint256 public totalDeposited;
    uint256 public totalLocked;
    uint256 public totalCredits;
    uint256 public totalWithdrawn;
    mapping(bytes32 => EpisodeView) private episodes;
    mapping(bytes32 => mapping(address => JurorVote)) private votes;
    mapping(bytes32 => Settlement) private settlements;
    bool private withdrawing;

    event EpisodeRegistered(bytes32 indexed episodeId, Config config, uint64 postingDeadline, uint256 jurorBond);
    event ClaimPosted(
        bytes32 indexed episodeId,
        address indexed creator,
        bytes32 contentHash,
        uint256 amount,
        uint64 challengeDeadline
    );
    event Challenged(
        bytes32 indexed episodeId,
        address indexed challenger,
        bytes32 evidenceHash,
        uint256 amount,
        uint64 commitDeadline,
        uint64 revealDeadline
    );
    event VoteCommitted(bytes32 indexed episodeId, address indexed juror, bytes32 commitment, uint256 bond);
    event VoteRevealed(
        bytes32 indexed episodeId, address indexed juror, uint8 verdict, bytes32 assessmentHash, bytes32 salt
    );
    event EpisodeSettled(
        bytes32 indexed episodeId, State outcome, address winner, uint8 creatorVotes, uint8 challengerVotes
    );
    event EpisodeExpired(bytes32 indexed episodeId, State outcome);
    event JurorForfeited(bytes32 indexed episodeId, address indexed juror, uint256 amount);
    event CreditAccrued(bytes32 indexed episodeId, address indexed recipient, uint256 amount);
    event Withdrawn(address indexed recipient, uint256 amount);

    constructor(address operator_) {
        if (operator_ == address(0)) revert InvalidConfiguration();
        operator = operator_;
    }

    function registerEpisode(bytes32 id, Config calldata config) external {
        if (msg.sender != operator) revert Unauthorized();
        if (episodes[id].state != State.Unknown) revert DuplicateEpisode();
        if (id == bytes32(0) || config.configurationHash == bytes32(0)) revert InvalidConfiguration();
        if (
            config.creator == address(0) || config.challenger == address(0) || config.treasury == address(0)
                || config.creator == config.challenger || config.creator == config.treasury
                || config.challenger == config.treasury || config.jurors.length < 3 || config.jurors.length > 7
                || config.jurors.length % 2 == 0
        ) revert InvalidConfiguration();
        if (
            config.beta == 0 || config.beta > type(uint256).max / 10000 || config.gammaBps == 0
                || config.gammaBps >= 10000 || uint256(config.winnerBps) + config.jurorBps + config.protocolBps != 10000
                || config.postingDuration == 0 || config.challengeDuration == 0 || config.commitDuration == 0
                || config.revealDuration == 0
        ) revert InvalidConfiguration();
        uint256 jurorBond = config.beta * config.gammaBps / 10000;
        uint256 maximumDuration =
            uint256(config.postingDuration) + config.challengeDuration + config.commitDuration + config.revealDuration;
        // Chain time is used only to prove every possible future deadline fits uint64.
        // forge-lint: disable-start(block-timestamp)
        if (
            jurorBond == 0 || block.timestamp > type(uint64).max || maximumDuration > type(uint64).max - block.timestamp
        ) revert InvalidConfiguration();
        // forge-lint: disable-end
        for (uint256 i; i < config.jurors.length; i++) {
            address juror = config.jurors[i];
            // The roster is capped at seven; invalid eligibility must reject registration atomically.
            // forge-lint: disable-start(require-revert-in-loop)
            if (
                juror == address(0) || juror == config.creator || juror == config.challenger || juror == config.treasury
            ) revert InvalidConfiguration();
            // forge-lint: disable-end
            for (uint256 j; j < i; j++) {
                // At most 21 roster pairs are checked; a duplicate cannot be deferred past registration.
                // forge-lint: disable-next-line(require-revert-in-loop)
                if (juror == config.jurors[j]) revert InvalidConfiguration();
            }
        }
        EpisodeView storage episode = episodes[id];
        episode.config = config;
        // Registration proved now + all four durations <= uint64.max above.
        // forge-lint: disable-next-line(unsafe-typecast)
        episode.postingDeadline = uint64(block.timestamp + config.postingDuration);
        episode.state = State.Registered;
        episode.jurorBond = jurorBond;
        emit EpisodeRegistered(id, config, episode.postingDeadline, jurorBond);
    }

    function postClaim(bytes32 id, bytes32 contentHash) external payable {
        EpisodeView storage episode = _episode(id);
        if (msg.sender != episode.config.creator) revert Unauthorized();
        // SPEC §7.2 defines an exclusive chain-time posting deadline, never a random seed.
        // forge-lint: disable-next-line(block-timestamp)
        if (episode.state != State.Registered || block.timestamp >= episode.postingDeadline) revert WrongPhase();
        if (msg.value != episode.config.beta) revert IncorrectDeposit();
        if (contentHash == bytes32(0)) revert InvalidHash();
        episode.contentHash = contentHash;
        // Posting precedes its deadline; registration reserved space for every later window.
        // forge-lint: disable-next-line(unsafe-typecast)
        episode.challengeDeadline = uint64(block.timestamp + episode.config.challengeDuration);
        episode.state = State.Open;
        _deposit(episode);
        emit ClaimPosted(id, msg.sender, contentHash, msg.value, episode.challengeDeadline);
    }

    function challenge(bytes32 id, bytes32 evidenceHash) external payable {
        EpisodeView storage episode = _episode(id);
        if (msg.sender != episode.config.challenger) revert Unauthorized();
        // SPEC §7.2 makes the challenge window depend on chain time, not validator randomness.
        // forge-lint: disable-next-line(block-timestamp)
        if (episode.state != State.Open || block.timestamp >= episode.challengeDeadline) revert WrongPhase();
        if (msg.value != episode.config.beta) revert IncorrectDeposit();
        if (evidenceHash == bytes32(0)) revert InvalidHash();
        episode.evidenceHash = evidenceHash;
        // Challenge precedes its deadline; registration also reserved the commit and reveal durations.
        // forge-lint: disable-next-line(unsafe-typecast)
        episode.commitDeadline = uint64(block.timestamp + episode.config.commitDuration);
        episode.revealDeadline = episode.commitDeadline + episode.config.revealDuration;
        episode.state = State.Commit;
        _deposit(episode);
        emit Challenged(id, msg.sender, evidenceHash, msg.value, episode.commitDeadline, episode.revealDeadline);
    }

    function commitVote(bytes32 id, bytes32 commitment) external payable {
        EpisodeView storage episode = _episode(id);
        // Chain time deliberately closes Commit exactly at the immutable deadline (SPEC §7.2).
        // forge-lint: disable-next-line(block-timestamp)
        if (episode.state != State.Commit || block.timestamp >= episode.commitDeadline) revert WrongPhase();
        if (!_isJuror(episode, msg.sender)) revert Unauthorized();
        if (msg.value != episode.jurorBond) revert IncorrectDeposit();
        if (commitment == bytes32(0)) revert InvalidHash();
        JurorVote storage vote = votes[id][msg.sender];
        if (vote.commitment != bytes32(0)) revert DuplicateAction();
        vote.commitment = commitment;
        _deposit(episode);
        emit VoteCommitted(id, msg.sender, commitment, msg.value);
    }

    function revealVote(bytes32 id, uint8 verdict, bytes32 assessmentHash, bytes32 salt) external {
        EpisodeView storage episode = _episode(id);
        // Reveal deliberately includes its start and excludes its end in chain time (SPEC §7.2).
        // forge-lint: disable-start(block-timestamp)
        if (
            episode.state != State.Commit || block.timestamp < episode.commitDeadline
                || block.timestamp >= episode.revealDeadline
        ) revert WrongPhase();
        // forge-lint: disable-end
        if (!_isJuror(episode, msg.sender)) revert Unauthorized();
        if (verdict > 1) revert InvalidVerdict();
        if (assessmentHash == bytes32(0)) revert InvalidHash();
        JurorVote storage vote = votes[id][msg.sender];
        if (vote.revealed) revert DuplicateAction();
        if (
            vote.commitment == bytes32(0)
                || vote.commitment != commitmentFor(id, msg.sender, verdict, assessmentHash, salt)
        ) {
            revert InvalidCommitment();
        }
        vote.revealed = true;
        vote.verdict = verdict;
        vote.assessmentHash = assessmentHash;
        if (verdict == 0) episode.creatorVotes++;
        else episode.challengerVotes++;
        emit VoteRevealed(id, msg.sender, verdict, assessmentHash, salt);
    }

    function settle(bytes32 id) external {
        EpisodeView storage episode = _episode(id);
        // Permissionless settlement opens at the fixed chain-time reveal deadline (SPEC §7.2).
        // forge-lint: disable-next-line(block-timestamp)
        if (episode.state != State.Commit || block.timestamp < episode.revealDeadline) revert WrongPhase();
        Settlement storage result = settlements[id];
        uint256 requiredVotes = episode.config.jurors.length / 2 + 1;
        if (episode.creatorVotes >= requiredVotes) {
            result.outcome = State.SettledCreator;
            result.winner = episode.config.creator;
        } else if (episode.challengerVotes >= requiredVotes) {
            result.outcome = State.SettledChallenger;
            result.winner = episode.config.challenger;
        } else {
            result.outcome = State.Aborted;
        }
        episode.state = result.outcome;
        totalLocked -= episode.lockedLiability;
        episode.lockedLiability = 0;

        if (result.outcome == State.Aborted) {
            _credit(id, episode, episode.config.creator, episode.config.beta);
            _credit(id, episode, episode.config.challenger, episode.config.beta);
        } else {
            uint256 qualified = uint256(episode.creatorVotes) + episode.challengerVotes;
            uint256 baseProtocol = episode.config.beta * episode.config.protocolBps / 10000;
            uint256 juryPool = episode.config.beta * episode.config.jurorBps / 10000;
            result.jurorReward = juryPool / qualified;
            result.protocolFee = baseProtocol + juryPool - qualified * result.jurorReward;
            result.winnerPayout = 2 * episode.config.beta - baseProtocol - juryPool;
            _credit(id, episode, result.winner, result.winnerPayout);
        }

        for (uint256 i; i < episode.config.jurors.length; i++) {
            address juror = episode.config.jurors[i];
            JurorVote storage vote = votes[id][juror];
            if (vote.revealed) {
                _credit(id, episode, juror, episode.jurorBond + result.jurorReward);
            } else if (vote.commitment != bytes32(0)) {
                result.forfeitedBonds += episode.jurorBond;
                emit JurorForfeited(id, juror, episode.jurorBond);
            }
        }
        _credit(id, episode, episode.config.treasury, result.protocolFee + result.forfeitedBonds);
        assert(episode.totalDeposited == episode.totalCredited);
        emit EpisodeSettled(id, result.outcome, result.winner, episode.creatorVotes, episode.challengerVotes);
    }

    function expire(bytes32 id) external {
        EpisodeView storage episode = _episode(id);
        State outcome;
        // Expiry uses inclusive immutable chain-time boundaries, never timing-derived randomness.
        // forge-lint: disable-start(block-timestamp)
        if (episode.state == State.Registered && block.timestamp >= episode.postingDeadline) {
            outcome = State.ExpiredUnfunded;
        } else if (episode.state == State.Open && block.timestamp >= episode.challengeDeadline) {
            outcome = State.ExpiredUnchallenged;
        } else {
            revert WrongPhase();
        }
        // forge-lint: disable-end
        episode.state = outcome;
        settlements[id].outcome = outcome;
        totalLocked -= episode.lockedLiability;
        episode.lockedLiability = 0;
        if (outcome == State.ExpiredUnchallenged) _credit(id, episode, episode.config.creator, episode.config.beta);
        assert(episode.totalDeposited == episode.totalCredited);
        emit EpisodeExpired(id, outcome);
    }

    function withdraw() external {
        if (withdrawing) revert ReentrantWithdrawal();
        uint256 amount = credits[msg.sender];
        if (amount == 0) revert NothingToWithdraw();
        withdrawing = true;
        credits[msg.sender] = 0;
        totalCredits -= amount;
        totalWithdrawn += amount;
        // The guard is already locked and liabilities debited; a failed transfer reverts every effect.
        // forge-lint: disable-next-line(reentrancy-eth)
        (bool success,) = msg.sender.call{value: amount}("");
        if (!success) revert TransferFailed();
        withdrawing = false;
        // Nested withdrawals are forbidden; record this withdrawal only after its transfer succeeds.
        // forge-lint: disable-next-line(reentrancy-events)
        emit Withdrawn(msg.sender, amount);
    }

    function getEpisode(bytes32 id) external view returns (EpisodeView memory episode) {
        episode = _episode(id);
        episode.state = phase(id);
    }

    function getJuror(bytes32 id, address juror) external view returns (JurorVote memory) {
        _episode(id);
        return votes[id][juror];
    }

    function getSettlement(bytes32 id) external view returns (Settlement memory) {
        _episode(id);
        return settlements[id];
    }

    function phase(bytes32 id) public view returns (State) {
        EpisodeView storage episode = _episode(id);
        // This view derives the phase from the same fixed chain-time boundary as action validation.
        // forge-lint: disable-next-line(block-timestamp)
        if (episode.state == State.Commit && block.timestamp >= episode.commitDeadline) return State.Reveal;
        return episode.state;
    }

    function commitmentFor(bytes32 id, address juror, uint8 verdict, bytes32 assessmentHash, bytes32 salt)
        public
        view
        returns (bytes32)
    {
        return keccak256(abi.encode(block.chainid, address(this), id, juror, verdict, assessmentHash, salt));
    }

    function _episode(bytes32 id) private view returns (EpisodeView storage episode) {
        episode = episodes[id];
        if (episode.state == State.Unknown) revert UnknownEpisode();
    }

    function _deposit(EpisodeView storage episode) private {
        episode.lockedLiability += msg.value;
        episode.totalDeposited += msg.value;
        totalDeposited += msg.value;
        totalLocked += msg.value;
    }

    function _isJuror(EpisodeView storage episode, address participant) private view returns (bool) {
        for (uint256 i; i < episode.config.jurors.length; i++) {
            if (episode.config.jurors[i] == participant) return true;
        }
        return false;
    }

    function _credit(bytes32 id, EpisodeView storage episode, address recipient, uint256 amount) private {
        if (amount == 0) return;
        credits[recipient] += amount;
        entitlement[id][recipient] += amount;
        episode.totalCredited += amount;
        totalCredits += amount;
        emit CreditAccrued(id, recipient, amount);
    }
}
